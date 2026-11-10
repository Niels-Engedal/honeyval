#!/usr/bin/env python3
"""Audit MITRE CAPEC and CWE as sources of potential enticingness CVP seeds.

Downloads *official structured MITRE source data* unless a local path is supplied.
No language-model rewriting and NO automatic enticingness labels: the original
fields are preserved so a human can judge candidate quality.

Example:
  python audit_security_seed_sources.py --source both --out seed_source_audit
  python audit_security_seed_sources.py --source capec --capec-file capec_latest.xml
  python audit_security_seed_sources.py --source cwe --cwe-file cwec_latest.xml.zip

Writes:
  counts.json                  per-source coverage and group breakdowns
  candidate_source_pairs.csv  all entries with BOTH an attack/weakness and a mitigation
  stratified_samples.csv      reproducible audit sample, stratified by source/abstraction
  all_entries.csv             complete extraction, including incomplete records

IMPORTANT: Attack-pattern prerequisites are not always vulnerabilities; defenses
are not always effective on their own. Review candidates before constructing CVP
positive and negative seeds.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

URLS = {
    "capec": "https://capec.mitre.org/data/xml/capec_latest.xml",
    "cwe": "https://cwe.mitre.org/data/xml/cwec_latest.xml.zip",
}
FIELDS = [
    "dataset", "id", "name", "abstraction", "status", "url", "likelihood",
    "description", "prerequisites", "mitigations", "has_description",
    "has_prerequisites", "has_mitigations", "candidate_pair",
    "candidate_positive_source", "candidate_negative_source",
]

def tag_name(elem):
    return elem.tag.rsplit("}", 1)[-1]

def child(parent, name):
    return next((e for e in parent if tag_name(e) == name), None)

def children(parent, name):
    if parent is None:
        return []
    return [e for e in parent if tag_name(e) == name]

def flatten(elem):
    if elem is None:
        return ""
    return re.sub(r"\s+", " ", " ".join(elem.itertext())).strip()

def section_texts(parent, container, leaf, fallback=None):
    sec = child(parent, container)
    if sec is None:
        return []
    vals = [flatten(x) for x in children(sec, leaf)]
    vals = [v for v in vals if v]
    if vals:
        return vals
    if fallback:
        vals = [flatten(x) for x in children(sec, fallback)]
        vals = [v for v in vals if v]
    return vals

def read_xml_bytes(source, local_path):
    if local_path:
        blob = Path(local_path).read_bytes()
        label = str(Path(local_path).resolve())
    else:
        url = URLS[source]
        print(f"Downloading {source.upper()} from {url} ...", flush=True)
        req = Request(url, headers={"User-Agent": "MITRE-Seed-Source-Audit/1.0"})
        with urlopen(req, timeout=90) as response:
            blob = response.read()
        label = url
    if zipfile.is_zipfile(io.BytesIO(blob)):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            matches = [n for n in z.namelist() if n.lower().endswith(".xml")]
            if not matches:
                raise ValueError(f"No XML inside {label}")
            name = max(matches, key=lambda n: z.getinfo(n).file_size)
            blob = z.read(name)
            label += "::" + name
    if not blob.lstrip().startswith((b"<?xml", b"<")):
        raise ValueError(f"Expected XML data in {label}")
    return blob, label

def capec_entries(root):
    for node in root.iter():
        if tag_name(node) != "Attack_Pattern":
            continue
        status = node.attrib.get("Status", "")
        if "deprecated" in status.lower() or "obsolete" in status.lower():
            continue
        ident = node.attrib.get("ID", "").strip()
        if not ident:
            continue
        desc = flatten(child(node, "Description"))
        prerequisites = section_texts(node, "Prerequisites", "Prerequisite")
        mitigations = section_texts(node, "Mitigations", "Mitigation")
        lik = flatten(child(node, "Likelihood_Of_Attack"))
        yield dict(
            dataset="CAPEC", id="CAPEC-" + ident, name=node.attrib.get("Name", ""),
            abstraction=node.attrib.get("Abstraction", ""), status=status,
            url=f"https://capec.mitre.org/data/definitions/{ident}.html",
            likelihood=lik, description=desc,
            prerequisites=" || ".join(prerequisites),
            mitigations=" || ".join(mitigations),
            # Keep original text rather than pretending these are polished labels.
            candidate_positive_source=("Attack: " + desc + " Prerequisites: " + " ; ".join(prerequisites)) if desc and prerequisites else "",
            candidate_negative_source=" ; ".join(mitigations[:3]),
        )

def cwe_entries(root):
    for node in root.iter():
        if tag_name(node) != "Weakness":
            continue
        status = node.attrib.get("Status", "")
        if "deprecated" in status.lower() or "obsolete" in status.lower():
            continue
        ident = node.attrib.get("ID", "").strip()
        if not ident:
            continue
        desc = flatten(child(node, "Description"))
        details = flatten(child(node, "Extended_Description"))
        mitigation_nodes = children(child(node, "Potential_Mitigations"), "Mitigation")
        mitigations = []
        for m in mitigation_nodes:
            mdesc = flatten(child(m, "Description"))
            if mdesc:
                mitigations.append(mdesc)
        yield dict(
            dataset="CWE", id="CWE-" + ident, name=node.attrib.get("Name", ""),
            abstraction=node.attrib.get("Abstraction", ""), status=status,
            url=f"https://cwe.mitre.org/data/definitions/{ident}.html",
            likelihood=flatten(child(node, "Likelihood_Of_Exploit")),
            description=desc + ((" " + details[:500]) if details else ""),
            prerequisites="", mitigations=" || ".join(mitigations),
            candidate_positive_source=desc,
            candidate_negative_source=" ; ".join(mitigations[:3]),
        )

def as_bool(x):
    return "1" if x else "0"

def complete(r):
    r["has_description"] = as_bool(bool(r["description"]))
    r["has_prerequisites"] = as_bool(bool(r["prerequisites"]))
    r["has_mitigations"] = as_bool(bool(r["mitigations"]))
    r["candidate_pair"] = as_bool(bool(r["candidate_positive_source"] and r["candidate_negative_source"]))
    return r

def write_csv(path, records):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({k: r.get(k, "") for k in FIELDS} for r in records)

def sample_stratified(rows, n_per_group, seed):
    rng = random.Random(seed)
    by_group = defaultdict(list)
    for r in rows:
        by_group[(r["dataset"], r["abstraction"] or "unknown")].append(r)
    out = []
    for group in sorted(by_group):
        pool = by_group[group]
        out += rng.sample(pool, min(n_per_group, len(pool)))
    return sorted(out, key=lambda r: (r["dataset"], r["abstraction"], r["id"]))

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["capec", "cwe", "both"], default="both")
    p.add_argument("--capec-file", help="Optional local CAPEC XML or ZIP; bypass download")
    p.add_argument("--cwe-file", help="Optional local CWE XML or ZIP; bypass download")
    p.add_argument("--out", default="seed_source_audit")
    p.add_argument("--per-group", type=int, default=25, help="Sample count per dataset/abstraction group")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    if args.per_group < 1:
        p.error("--per-group must be >= 1")
    sources = ["capec", "cwe"] if args.source == "both" else [args.source]
    rows, counts = [], {"note": "Coverage, NOT semantic suitability. Review each source field; no automatic labels.", "sources": {}}
    for source in sources:
        blob, origin = read_xml_bytes(source, getattr(args, f"{source}_file"))
        root = ET.fromstring(blob)
        extracted = [complete(r) for r in (capec_entries(root) if source == "capec" else cwe_entries(root))]
        rows.extend(extracted)
        counts["sources"][source] = {
            "input": origin, "catalog_version": root.attrib.get("Version", "unknown"),
            "nondeprecated_entries": len(extracted),
            "with_description": sum(r["has_description"] == "1" for r in extracted),
            "with_prerequisites": sum(r["has_prerequisites"] == "1" for r in extracted),
            "with_mitigation": sum(r["has_mitigations"] == "1" for r in extracted),
            "candidate_source_pairs": sum(r["candidate_pair"] == "1" for r in extracted),
            "by_abstraction": dict(Counter(r["abstraction"] or "unknown" for r in extracted)),
            "candidate_pairs_by_abstraction": dict(Counter(r["abstraction"] or "unknown" for r in extracted if r["candidate_pair"] == "1")),
        }
        print(f"{source.upper()}: {len(extracted)} nondeprecated entries; "
              f"{counts['sources'][source]['candidate_source_pairs']} raw candidate source pairs")

    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    candidates = [r for r in rows if r["candidate_pair"] == "1"]
    with (dest / "counts.json").open("w", encoding="utf-8") as f:
        json.dump(counts, f, ensure_ascii=False, indent=2)
    write_csv(dest / "all_entries.csv", rows)
    write_csv(dest / "candidate_source_pairs.csv", candidates)
    write_csv(dest / "stratified_samples.csv", sample_stratified(candidates, args.per_group, args.seed))
    print(f"Saved reports to {dest.resolve()}")
    print("IMPORTANT: source fields are NOT ready-to-embed positive/negative seeds. Review and normalize them first.")

if __name__ == "__main__":
    main()
