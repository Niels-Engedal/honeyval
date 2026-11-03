#!/usr/bin/env python3
"""Prepare a named, isolated Potato task from Honeyval strategy records.

Accepts CSV/JSONL, or pandas Parquet/pickle output from 01_preproc.py.
Uses only the Python standard library. Does not execute Honeyval agents.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
from collections import Counter
from pathlib import Path


def find_input(path: Path) -> Path:
    if path.is_file() and path.suffix.lower() in {".csv", ".jsonl", ".parquet", ".pkl"}:
        return path
    if path.is_dir():
        for filename in ("decisions.csv", "statements.csv", "statements_nlp.parquet",
                         "statements_nlp.pkl", "statements.parquet", "statements.pkl",
                         "strategies.jsonl"):
            candidate = path / filename
            if candidate.is_file():
                return candidate
    raise SystemExit(
        "--input must point to a .csv/.jsonl file, or an analysis directory "
        "with decisions.csv, statements.csv, statements_nlp.parquet/.pkl, "
        "or strategies.jsonl. "
        "For raw results/, run 01_prepare_data.py first."
    )


def iter_records(path: Path):
    if path.suffix.lower() in {".parquet", ".pkl"}:
        try:
            import pandas as pd
        except ImportError as exc:
            raise SystemExit("Parquet/pickle input requires pandas in this Python environment.") from exc
        if path.suffix.lower() == ".pkl":
            # pandas.read_pickle is unsafe for untrusted input; only use local generated files.
            frame = pd.read_pickle(path)
        else:
            frame = pd.read_parquet(path)
        yield from frame.to_dict(orient="records")
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        if path.suffix.lower() == ".csv":
            yield from csv.DictReader(handle)
        else:
            for i, line in enumerate(handle, 1):
                if line.strip():
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError(f"JSONL line {i} must be an object")
                    yield record


def first(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and not (isinstance(value, float) and math.isnan(value)) and str(value).strip():
            return str(value).strip()
    return ""


def prepare(args: argparse.Namespace) -> tuple[Path, Counter]:
    input_file = find_input(args.input.expanduser().resolve())
    root = args.output_root.expanduser().resolve()
    target = root / args.name
    if target.exists():
        raise SystemExit(
            f"Dataset already exists: {target}\n"
            "Choose a new --name. Existing annotation state is never overwritten."
        )

    records = []
    skipped = Counter()
    for idx, row in enumerate(iter_records(input_file), 1):
        role = first(row, "role", "actor", "agent", "agent_role").lower()
        if role not in {"attacker", "defender"}:
            skipped["unrecognized_role"] += 1
            continue
        if args.role != "both" and role != args.role:
            skipped["role_filter"] += 1
            continue
        source = first(row, "strategy_source")
        if args.source != "all" and source and source != args.source:
            skipped["source_filter"] += 1
            continue
        strategy = first(row, "strategy", "strategy_text", "statement_text", "text")
        if not strategy:
            skipped["empty_strategy"] += 1
            continue
        version = first(row, "strategy_prompt_version") or "unspecified"
        meta = {key: first(row, key) for key in (
            "experiment", "trajectory_id", "interaction_id", "turn_id",
            "exchange_id", "config", "app", "run", "sample",
            "step", "statement_order", "event", "strategy_source",
            "strategy_prompt_version",
        )}
        existing_id = first(row, "statement_id", "decision_id", "id")
        # The index disambiguates otherwise identical rows in the same input file.
        signature = json.dumps([existing_id, role, meta, strategy, idx], sort_keys=True)
        stable_id = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]
        text = f"{role.upper()} STRATEGY\n\n{strategy}"
        if args.include_context:
            context = first(row, "observation", "request", "context")
            if context:
                text = (f"PRIOR CONTEXT (truncated to {args.context_chars} chars):\n"
                        f"{context[:args.context_chars]}\n\n{role.upper()} STRATEGY:\n{strategy}")
        records.append({
            "id": f"{args.name}-{stable_id}",
            "text": text,
            "role": role,
            "strategy": strategy,
            **meta,
            "strategy_prompt_version": version,
        })

    if not records:
        raise SystemExit(f"No annotatable strategies found in {input_file}. Skipped: {dict(skipped)}")

    versions = sorted({r["strategy_prompt_version"] for r in records})
    if len(versions) > 1 and not args.allow_mixed_protocols:
        raise SystemExit(
            f"Multiple strategy prompt versions detected: {versions}. "
            "Select a single dataset/protocol or explicitly use --allow-mixed-protocols."
        )

    if args.limit and args.limit < len(records):
        rng = random.Random(args.random_seed)
        records = rng.sample(records, args.limit)

    target.mkdir(parents=True, exist_ok=False)
    with (target / "data.jsonl").open("w", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    task_name = json.dumps(f"Honeyval: {args.name}")
    config = f'''annotation_task_name: {task_name}
task_dir: "."
port: {args.port}

data_files:
  - data.jsonl
item_properties:
  id_key: id
  text_key: text
output_annotation_dir: annotation_output/
export_annotation_format: jsonl

user_config:
  allow_all_users: true
  users: []
require_password: false
max_annotations_per_user: 10000
max_annotations_per_item: 3

annotation_schemes:
  - annotation_type: likert
    name: believability
    description: "Attacker: expressed confidence the environment is genuine. Defender: intention to appear genuine. If unassessable, leave unrated."
    min_label: "Very low"
    max_label: "Very high"
    size: 5

  - annotation_type: likert
    name: enticingness
    description: "Attacker: expressed interest in pursuing the opportunity. Defender: intention to attract investigation. If unassessable, leave unrated."
    min_label: "Very low"
    max_label: "Very high"
    size: 5

  - annotation_type: radio
    name: seed_candidate
    description: "Is this statement a strong candidate for a CVP seed?"
    labels:
      - "Yes"
      - "No"
      - "Unsure"

  - annotation_type: text
    name: notes
    description: "Optional annotation notes"
'''
    (target / "config.yaml").write_text(config, encoding="utf-8")
    manifest = {
        "input": str(input_file),
        "source_sha256": hashlib.sha256(input_file.read_bytes()).hexdigest(),
        "name": args.name,
        "total": len(records),
        "roles": dict(Counter(r["role"] for r in records)),
        "strategy_prompt_versions": versions,
        "source_filter": args.source,
        "include_context": args.include_context,
        "skipped": dict(skipped),
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return target, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="Prepared decisions.csv, statements_nlp.parquet/.pkl, JSONL or analysis folder")
    parser.add_argument("--name", required=True,
                        help="Unique dataset/run name (letters, digits, hyphen, underscore)")
    parser.add_argument("--output-root", type=Path,
                        default=Path(__file__).resolve().parent / "datasets")
    parser.add_argument("--role", choices=("both", "attacker", "defender"), default="both")
    parser.add_argument("--source", choices=("contemporaneous", "retrospective", "all"),
                        default="contemporaneous")
    parser.add_argument("--limit", type=int, default=None,
                        help="Optional random pilot sample (reproducible via --random-seed)")
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--include-context", action="store_true",
                        help="Include preceding observation/request from prepared data in displayed text")
    parser.add_argument("--context-chars", type=int, default=1200)
    parser.add_argument("--allow-mixed-protocols", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.name):
        parser.error("--name must be 1–80 characters: letters, digits, '-' or '_'")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.context_chars < 1 or not 1 <= args.port <= 65535:
        parser.error("--context-chars must be positive, and --port must be 1–65535")
    directory, skipped = prepare(args)
    print(f"Prepared dataset: {directory}")
    print(f"Skipped: {dict(skipped)}")
    print(f"Validate: potato validate '{directory / 'config.yaml'}'")
    print(f"Launch:   potato start '{directory / 'config.yaml'}'")


if __name__ == "__main__":
    main()