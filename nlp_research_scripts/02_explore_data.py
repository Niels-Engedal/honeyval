"""NLP RESEARCH EXTENSION: descriptive inspection of prepared Honeyval results.

Standard-library exploratory report; no embeddings or unverified deception labels.
Run 01_prepare_data.py first. Unit of analysis is the trajectory; do not treat
individual decisions from one trajectory as independent samples.
"""
import argparse
import csv
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
