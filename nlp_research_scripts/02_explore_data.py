"""NLP RESEARCH EXTENSION: descriptive inspection of prepared Honeyval results.

Standard-library exploratory report; no embeddings or unverified deception labels.
Run 01_prepare_data.py first. Unit of analysis is the trajectory; do not treat
individual decisions from one trajectory as independent samples.
"""
import argparse
import csv
import re
from statistics import mean, median
from collections import Counter, defaultdict
from pathlib import Path


def read_csv(path):
    if not path.is_file():
        raise SystemExit(f"Missing {path}. Run 01_prepare_data.py first.")
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def yes(value):
    return str(value).lower() in {"true", "1", "yes"}


def percentage(n, total):
    return f"{n}/{total} ({100*n/total:.1f}%)" if total else "0/0 (n/a)"


def parse_failure_reason(raw):
    """Diagnose model text after stripping STRATEGY, using Honeyval's XML grammar."""
    if not raw.strip():
        return "empty model generation"
    clean = re.sub(r"<STRATEGY>.*?</STRATEGY>", "", raw, flags=re.I | re.S).strip()
    if not clean:
        return "strategy only; no ACTION"
    block = re.findall(r"<ACTION>(.*?)</ACTION>", clean, flags=re.S)
    if not block:
        return "missing complete ACTION block"
    action = block[-1]
    names = re.findall(r"<ACTION_NAME>(.*?)</ACTION_NAME>", action, flags=re.S)
    bodies = re.findall(r"<ACTION_BODY>(.*?)</ACTION_BODY>", action, flags=re.S)
    if not names or not bodies or len(names) != len(bodies):
        return "missing/mismatched ACTION_NAME or ACTION_BODY"
    if names[-1].strip() == "TOOL":
        tool = re.findall(r"<TOOL>(.*?)</TOOL>", bodies[-1], flags=re.S)
        if not tool:
            return "TOOL action missing complete TOOL block"
        names = re.findall(r"<TOOL_NAME>(.*?)</TOOL_NAME>", tool[-1], flags=re.S)
        inputs = re.findall(r"<TOOL_INPUT>(.*?)</TOOL_INPUT>", tool[-1], flags=re.S)
        if not names or not inputs or len(names) != len(inputs):
            return "missing/mismatched TOOL_NAME or TOOL_INPUT"
    return "unclassified (inspect raw generation)"


def explore(source):
    decisions = read_csv(source / "decisions.csv")
    paired = read_csv(source / "paired_exchanges.csv")
    trajectories = read_csv(source / "trajectories.csv")
    if not trajectories:
        raise SystemExit("No trajectories found")
    report = ["# NLP Honeyval pilot — descriptive audit", "",
              "This is a descriptive pilot report, not a test of the research hypotheses.",
              "Model-produced STRATEGY summaries are elicited self-reports, not hidden reasoning.",
              "Treat trajectories, not individual decision rows, as the independent sampling units.", ""]
    report += [f"**Trajectories:** {len(trajectories)}", "",
               "## Coverage and alignment", ""]
    for role in ("attacker", "defender"):
        rows = [r for r in decisions if r["role"] == role]
        captured = sum(bool(r["strategy"].strip()) for r in rows)
        report.append(f"- {role.title()} strategies: {percentage(captured, len(rows))}")
    matched = sum(yes(r["matched"]) for r in paired)
    completed = sum(yes(r["complete_pair"]) for r in paired)
    report += [f"- Defender events linked to attacker actions: {percentage(matched, len(paired))}",
               f"- Complete paired STRATEGY observations: {percentage(completed, len(paired))}",
               "- Some attacker requests may bypass the LLM defender (e.g., /docs, /openapi.json).",
               "", "## Results by application", "",
               "| Application | Trajectories | Attacker decisions | Defender decisions | Complete pairs |",
               "| --- | ---: | ---: | ---: | ---: |"]
    for app in sorted({r["app"] for r in trajectories}):
        a = sum(r["role"] == "attacker" and r["app"] == app for r in decisions)
        d = sum(r["role"] == "defender" and r["app"] == app for r in decisions)
        c = sum(r["app"] == app and yes(r["complete_pair"]) for r in paired)
        t = sum(r["app"] == app for r in trajectories)
        report.append(f"| {app} | {t} | {a} | {d} | {c} |")
    report += ["", "## Event and HTTP response distributions", ""]
    for role in ("attacker", "defender"):
        counts = Counter(r["event"] for r in decisions if r["role"] == role)
        report.append(f"- {role.title()} events: {dict(counts)}")
    statuses = Counter(r["status"] or "missing" for r in paired)
    report.append(f"- LLM defender HTTP statuses: {dict(statuses)}")
    errors = sum(bool(r["task_errors"] and r["task_errors"] != "0") for r in trajectories)
    capped = sum(yes(r["max_step_termination"]) for r in trajectories)
    report += ["", "## Termination and interpretation", "",
               f"- Trajectories with reported task errors: {errors}",
               f"- Trajectories stopped at configured step cap: {capped} (right-censored, not natural endings)",
               "- Do not interpret normal 400/401 responses as verified deception without annotation.",
               "- For RQ5 compare comparable EARLY turns, not pooled entire trajectories.",
               "- Confirm whether there is sufficient variation in termination lengths before testing RQ5.",
               "", "## Strategy coverage by decision index", "",
               "| Role | Step | Captured | Total |", "| --- | ---: | ---: | ---: |"]
    grouped = defaultdict(list)
    for r in decisions:
        grouped[(r["role"], int(r["step"]))].append(r)
    for (role, step), group in sorted(grouped.items()):
        captured = sum(bool(r["strategy"].strip()) for r in group)
        report.append(f"| {role} | {step} | {captured} | {len(group)} |")
    # Research QC: a strategy can be present even if the ACTION is unparseable.
    parser_failures = [r for r in decisions
                       if r["role"] == "attacker" and r["event"] == "PARSING ERROR"]
    reasons = Counter(parse_failure_reason(r["raw_response"]) for r in parser_failures)
    failure_by_app = Counter(r["app"] for r in parser_failures)
    per_trajectory = defaultdict(int)
    for r in parser_failures:
        per_trajectory[r["trajectory_id"]] += 1
    n_affected = len(per_trajectory)
    report += ["", "## Attacker parsing-error diagnostic", "",
               f"- Parsing errors: {len(parser_failures)} / "
               f"{sum(r['role']=='attacker' for r in decisions)} attacker decisions.",
               f"- Affected trajectories: {n_affected} / {len(trajectories)}.",
               "- These are failures to parse a model-generated ACTION, NOT "
               "a failed attack or an exception that stops the experiment.",
               "- STRATEGY presence does not imply ACTION validity.",
               f"- Failures by application: {dict(failure_by_app)}.",
               f"- Likely format causes (diagnostic heuristics): {dict(reasons)}.",
               ""]
    lengths = defaultdict(list)
    defender_lengths = defaultdict(list)
    giveups = defaultdict(int)
    for r in trajectories:
        lengths[r["app"]].append(int(r["attacker_decisions"]))
        defender_lengths[r["app"]].append(int(r["defender_decisions"]))
        if any(d["event"] == "GIVEUP" and d["trajectory_id"] == r["trajectory_id"]
               for d in decisions):
            giveups[r["app"]] += 1
    report += ["## Trajectory lengths and explicit give-ups", "",
               "| Application | Attacker steps: min / median / max | Defender events: min / median / max | Explicit GIVEUP |",
               "| --- | --- | --- | ---: |"]
    for app in sorted(lengths):
        a = lengths[app]
        d = defender_lengths[app]
        report.append(f"| {app} | {min(a)} / {median(a):g} / {max(a)} "
                      f"| {min(d)} / {median(d):g} / {max(d)} "
                      f"| {giveups[app]} / {len(a)} |")
    report += ["", "GIVEUP is an explicit attacker terminal action, not proof "
               "that the honeypot successfully deceived it. "
               "Parsing errors may consume steps and influence abandonment.", ""]
    report += ["", "## Next NLP stage", "",
               "Calculate sentence embeddings only for complete, correctly aligned pairs; keep missingness indicators.",
               "Validate role-/app-/turn-matched random-pair baselines before interpreting cosine trends.",
               "For suspicion/deception, create human labels and evaluate agreement/classification separately.", ""]
    text = "\n".join(report)
    (source / "pilot_report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"\nReport saved: {source / 'pilot_report.md'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("analysis_outputs/latest"),
                        help="Directory containing prepared CSV files")
    args = parser.parse_args()
    explore(args.input)
