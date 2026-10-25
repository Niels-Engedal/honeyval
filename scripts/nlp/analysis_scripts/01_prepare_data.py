"""NLP RESEARCH EXTENSION: prepare Honeyval JSONL for descriptive NLP work.

Reads a results/<experiment> directory OR a ZIP of that directory. Uses only
Python standard library. Does not import/run the Honeyval agents.

Attacker and defender model calls MUST NOT be paired by row number: the proxy
handles some URLs without invoking the defender LLM. Pair by in-run timestamps
and retain unmatched records and warnings for auditing.
"""
import argparse
import ast
import csv
import json
import re
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

CONTROL_EVENTS = {"START", "END", "ERROR", "RATE_LIMIT_ERROR"}


def csv_write(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_lines(content):
    return [json.loads(line) for line in content.splitlines() if line.strip()]


def sources(path):
    """Yield (task relative path, filename-to-content reader) without extracting ZIPs."""
    if path.is_file() and path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            entries = set(archive.namelist())
            for filename in sorted(entries):
                if not filename.endswith("metadata-logs/agent-metadata.jsonl"):
                    continue
                task = PurePosixPath(filename).parent.parent
                def reader(name, task=task):
                    member = str(task / name)
                    return archive.read(member).decode("utf-8") if member in entries else None
                yield str(task), reader
    elif path.is_dir():
        for agent_file in sorted(path.rglob("agent-metadata.jsonl")):
            if agent_file.parent.name != "metadata-logs":
                continue
            task = agent_file.parent.parent
            def reader(name, task=task):
                item = task / name
                return item.read_text(encoding="utf-8") if item.is_file() else None
            yield str(task.relative_to(path)), reader
    else:
        raise SystemExit("--input must be an experiment directory or a ZIP file")


def metadata(reader, name):
    content = reader("metadata-logs/" + name)
    return read_lines(content) if content else []


def endpoint_from_request(raw):
    try:
        request = ast.literal_eval(raw)
        if isinstance(request, dict):
            return str(request.get("endpoint") or "")
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        pass
    return ""


def count_task_errors(raw):
    match = re.search(r"Task finished\. Number of errors:\s*(\d+)", raw or "")
    return int(match.group(1)) if match else ""


def load_json(content):
    if not content:
        return {}
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return {}


def prepare(input_path, output):
    decisions, pairs, trajectories, warnings = [], [], [], []
    seen = 0
    for task_path, read in sources(input_path):
        seen += 1
        parts = PurePosixPath(task_path).parts
        if len(parts) < 4:
            warnings.append(f"Unrecognized path structure: {task_path}")
            continue
        config, app, sample = parts[-4], parts[-3], parts[-2]
        experiment = parts[-5] if len(parts) >= 5 else input_path.stem
        trajectory_id = "/".join(parts[-5:] if len(parts) >= 5 else (experiment, *parts))
        attacker = [r for r in metadata(read, "agent-metadata.jsonl") if r.get("event") not in CONTROL_EVENTS]
        defender = [r for r in metadata(read, "http-app-metadata.jsonl") if r.get("event") not in CONTROL_EVENTS]
        for role, rows in (("attacker", attacker), ("defender", defender)):
            for step, r in enumerate(rows, 1):
                decisions.append({
                    "trajectory_id": trajectory_id, "experiment": experiment,
                    "config": config, "app": app, "sample": sample,
                    "role": role, "step": step, "event": r.get("event", ""),
                    "time_in": r.get("time_in", ""), "time_out": r.get("time_out", ""),
                    "strategy": r.get("strategy") or "",
                    "strategy_source": r.get("strategy_source") or "unrecorded",
                    "strategy_prompt_version": r.get("strategy_prompt_version") or "unversioned",
                    "strategy_valid": bool(r.get("strategy")),
                    "raw_response": r.get("strategy_initial_response") or r.get("raw_response") or "",
                    "action_body": r.get("action_body") if role == "attacker" else "",
                    "observation": r.get("env_response") if role == "attacker" else r.get("out", ""),
                    "request": r.get("in", "") if role == "defender" else "",
                    "tokens_consumed": r.get("tokens_consumed", ""),
                    "tokens_generated": r.get("tokens_generated", ""),
                })

        # The LLM defender may not be called for every attacker action. Its
        # time_in occurs during the tool execution, between attacker time_in and
        # attacker time_out. A single tool call can also trigger >1 HTTP calls.
        paired_defender = set()
        for d_idx, d in enumerate(defender):
            d_time = d.get("time_in")
            matches = []
            if isinstance(d_time, (int, float)):
                matches = [(a_idx, a) for a_idx, a in enumerate(attacker)
                           if isinstance(a.get("time_in"), (int, float))
                           and isinstance(a.get("time_out"), (int, float))
                           and a["time_in"] <= d_time <= a["time_out"] + 0.25]
            if len(matches) != 1:
                warnings.append(f"{trajectory_id}: defender {d_idx+1} has {len(matches)} matching attacker windows")
            a_idx, a = matches[0] if len(matches) == 1 else (None, {})
            if a_idx is not None:
                paired_defender.add(d_idx)
            endpoint = endpoint_from_request(d.get("in", ""))
            action = str(a.get("action_body") or "")
            if a_idx is not None and endpoint and endpoint not in action:
                warnings.append(f"{trajectory_id}: endpoint {endpoint} not visible in attacker action {a_idx+1}")
            a_strategy = a.get("strategy") or ""
            d_strategy = d.get("strategy") or ""
            status_match = re.search(r"<STATUS>\s*(\d+)\s*</STATUS>", str(d.get("out") or ""))
            pairs.append({
                "trajectory_id": trajectory_id, "experiment": experiment,
                "config": config, "app": app, "sample": sample,
                "attacker_step": a_idx+1 if a_idx is not None else "",
                "defender_step": d_idx+1,
                "matched": a_idx is not None,
                "complete_pair": bool(a_strategy and d_strategy and a_idx is not None),
                "endpoint": endpoint,
                "status": status_match.group(1) if status_match else "",
                "attacker_strategy": a_strategy,
                "defender_strategy": d_strategy,
                "attacker_strategy_prompt_version": a.get("strategy_prompt_version") or "unversioned",
                "defender_strategy_prompt_version": d.get("strategy_prompt_version") or "unversioned",
                "attacker_action": action,
                "defender_response": d.get("out") or "",
                "attacker_time_in": a.get("time_in", ""),
                "defender_time_in": d.get("time_in", ""),
            })
        metrics = load_json(read("exploit-metrics-agent.json"))
        agent_metrics = load_json(read("agent-only-metrics.json"))
        defender_metrics = load_json(read("http-app-only-metrics.json"))
        log = read("logs/agent.log") or ""
        trajectories.append({
            "trajectory_id": trajectory_id, "experiment": experiment,
            "config": config, "app": app, "sample": sample,
            "attacker_decisions": len(attacker), "defender_decisions": len(defender),
            "strategy_prompt_versions": ",".join(sorted({r.get("strategy_prompt_version") or "unversioned" for r in attacker + defender})),
            "attacker_strategies": sum(bool(r.get("strategy")) for r in attacker),
            "defender_strategies": sum(bool(r.get("strategy")) for r in defender),
            "matched_defender_decisions": len(paired_defender),
            "complete_strategy_pairs": sum(p["complete_pair"] for p in pairs if p["trajectory_id"] == trajectory_id),
            "task_errors": count_task_errors(read("task.log")),
            "max_step_termination": "Maximum number of steps reached" in log,
            "agent_success": metrics.get("agent_success", ""),
            "agent_giveup": metrics.get("agent_giveup", ""),
            "attacker_cost_usd": agent_metrics.get("total_dollar_cost", ""),
            "defender_cost_usd": defender_metrics.get("total_dollar_cost", ""),
        })
    if not seen:
        raise SystemExit("No agent-metadata.jsonl found in --input")

    csv_write(output / "decisions.csv", decisions, [
        "trajectory_id", "experiment", "config", "app", "sample", "role",
        "step", "event", "time_in", "time_out", "strategy", "strategy_source",
        "strategy_prompt_version", "strategy_valid", "raw_response", "action_body", "observation",
        "request", "tokens_consumed", "tokens_generated",
    ])
    csv_write(output / "paired_exchanges.csv", pairs, [
        "trajectory_id", "experiment", "config", "app", "sample",
        "attacker_step", "defender_step", "matched", "complete_pair",
        "endpoint", "status", "attacker_strategy", "defender_strategy",
        "attacker_strategy_prompt_version", "defender_strategy_prompt_version",
        "attacker_action", "defender_response", "attacker_time_in", "defender_time_in",
    ])
    csv_write(output / "trajectories.csv", trajectories, [
        "trajectory_id", "experiment", "config", "app", "sample",
        "attacker_decisions", "defender_decisions", "strategy_prompt_versions", "attacker_strategies",
        "defender_strategies", "matched_defender_decisions", "complete_strategy_pairs",
        "task_errors", "max_step_termination", "agent_success", "agent_giveup",
        "attacker_cost_usd", "defender_cost_usd",
    ])
    (output / "warnings.txt").write_text("\n".join(warnings) + ("\n" if warnings else ""), encoding="utf-8")
    print(f"Prepared {len(trajectories)} trajectories | {len(decisions)} decisions | "
          f"{len(pairs)} defender events | {sum(p['complete_pair'] for p in pairs)} complete strategy pairs")
    print(f"CSV files written to {output} (warnings: {len(warnings)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Experiment results folder or ZIP")
    parser.add_argument("--output", type=Path, default=Path("analysis_outputs/latest"))
    args = parser.parse_args()
    prepare(args.input, args.output)
