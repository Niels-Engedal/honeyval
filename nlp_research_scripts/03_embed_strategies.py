"""NLP RESEARCH EXTENSION — exploratory Sentence-BERT strategy alignment.

Run 01_prepare_data.py first. Encodes model-generated STRATEGY summaries as
sentences; cosine similarity is semantic relatedness, not agreement,
intent, deception, or causation.

Unit of replication: trajectory. Observations within a trajectory are NOT
independent; matched baseline is estimated within application, configuration,
and exact attacker step using defender texts from OTHER trajectories.

Requires: numpy, sentence-transformers (install in the honeyval environment).
Outputs pair-level cosine scores, per-turn descriptive means and a Markdown
report. Unpaired/missing strategies are retained in original preparation CSVs.
"""
import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean

import numpy as np


def rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write(path, data, fields):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)


def valid(value):
    return str(value).lower() in ("true", "1", "yes")


def interval(values, replicates, seed):
    """Percentile cluster bootstrap, one score per independently run trajectory."""
    if not values:
        return None
    rng = random.Random(seed)
    if len(values) == 1:
        return None
    distribution = []
    for _ in range(replicates):
        distribution.append(mean(rng.choices(values, k=len(values))))
    distribution.sort()
    return (
        distribution[int(0.025 * (len(distribution) - 1))],
        distribution[int(0.975 * (len(distribution) - 1))],
    )


def estimate_slope(data):
    """OLS slope of within-trajectory cosine versus defender turn index."""
    if len(data) < 3:
        return None
    x = np.asarray([a for a, _ in data], dtype=float)
    y = np.asarray([b for _, b in data], dtype=float)
    x = x - x.mean()
    denom = float(x @ x)
    return float(x @ (y - y.mean()) / denom) if denom > 0 else None


def run(source, model_id, bootstrap, seed):
    pairs = rows(source / "paired_exchanges.csv")
    decisions = rows(source / "decisions.csv")
    trajectories = rows(source / "trajectories.csv")

    complete = [p for p in pairs
                if valid(p["matched"]) and valid(p["complete_pair"])
                and p["attacker_step"].strip()
                and p["attacker_strategy"].strip()
                and p["defender_strategy"].strip()]
    if not complete:
        raise SystemExit("No complete matched strategy pairs. Recheck script 01.")

    # All supplied texts are summaries emitted by the model, not hidden reasoning.
    following = {
        (r["trajectory_id"], r["step"]): r["strategy"].strip()
        for r in decisions
        if r["role"] == "attacker" and r["strategy"].strip()
    }
    text_set = set()
    for p in complete:
        text_set.add(p["attacker_strategy"].strip())
        text_set.add(p["defender_strategy"].strip())
        nxt = following.get((p["trajectory_id"], str(int(p["attacker_step"]) + 1)))
        if nxt:
            text_set.add(nxt)
    texts = sorted(text_set)

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit(
            "Install the analysis dependency first:\n"
            "python -m pip install sentence-transformers\n"
            "(Then rerun this script.)"
        ) from exc
    print(f"Encoding {len(texts)} distinct strategies with {model_id}...")
    encoder = SentenceTransformer(model_id)
    vectors = np.asarray(
        encoder.encode(texts, convert_to_numpy=True,
                       normalize_embeddings=True, show_progress_bar=True),
        dtype=np.float32,
    )
    lookup = {s: vectors[i] for i, s in enumerate(texts)}

    def cosine(a, b):
        return float(np.clip(lookup[a.strip()] @ lookup[b.strip()], -1.0, 1.0))

    # Negative reference text: same app, configuration, exact attacker step,
    # but sourced from a different trajectory, not the actual responding agent.
    pools = defaultdict(list)
    for p in complete:
        key = (p["app"], p["config"], int(p["attacker_step"]))
        pools[key].append(p)

    output = []
    for p in complete:
        a = p["attacker_strategy"]
        d = p["defender_strategy"]
        key = (p["app"], p["config"], int(p["attacker_step"]))
        negatives = [
            q for q in pools[key]
            if q["trajectory_id"] != p["trajectory_id"]
        ]
        baseline = (mean(cosine(a, q["defender_strategy"]) for q in negatives)
                    if negatives else None)
        score = cosine(a, d)
        nxt = following.get((p["trajectory_id"], str(int(p["attacker_step"]) + 1)))
        lagged = cosine(d, nxt) if nxt else None
        output.append({
            "trajectory_id": p["trajectory_id"],
            "config": p["config"], "app": p["app"], "sample": p["sample"],
            "attacker_step": p["attacker_step"],
            "defender_step": p["defender_step"],
            "endpoint": p["endpoint"], "status": p["status"],
            "cosine_attacker_defender": score,
            "cosine_matched_other_trajectory": baseline if baseline is not None else "",
            "cosine_delta_vs_reference": score - baseline if baseline is not None else "",
            "n_reference_defender_texts": len(negatives),
            "cosine_defender_next_attacker": lagged if lagged is not None else "",
            "has_following_attacker_strategy": bool(nxt),
        })

    fields = list(output[0])
    write(source / "03_pair_similarities.csv", output, fields)

    by_turn = defaultdict(list)
    by_trajectory = defaultdict(list)
    for p in output:
        by_turn[(p["app"], int(p["defender_step"]))].append(p)
        by_trajectory[p["trajectory_id"]].append(p)

    turn_rows = []
    for (app, turn), ps in sorted(by_turn.items()):
        scores = [p["cosine_attacker_defender"] for p in ps]
        deltas = [p["cosine_delta_vs_reference"] for p in ps
                  if isinstance(p["cosine_delta_vs_reference"], (int, float))]
        turn_rows.append({
            "app": app, "defender_step": turn, "n_pairs": len(scores),
            "mean_same_exchange_cosine": mean(scores),
            "mean_delta_vs_reference": mean(deltas) if deltas else "",
            "n_reference_comparisons": len(deltas),
        })
    write(source / "03_similarity_by_turn.csv", turn_rows, list(turn_rows[0]))

    length_by_id = {
        r["trajectory_id"]: int(r["attacker_decisions"])
        for r in trajectories
    }
    trajectory_rows = []
    for tid, ps in sorted(by_trajectory.items()):
        scores = [p["cosine_attacker_defender"] for p in ps]
        deltas = [p["cosine_delta_vs_reference"] for p in ps
                  if isinstance(p["cosine_delta_vs_reference"], (int, float))]
        lagged = [p["cosine_defender_next_attacker"] for p in ps
                  if isinstance(p["cosine_defender_next_attacker"], (int, float))]
        slope = estimate_slope([
            (int(p["defender_step"]), p["cosine_attacker_defender"])
            for p in ps
        ])
        trajectory_rows.append({
            "trajectory_id": tid, "app": ps[0]["app"], "n_pairs": len(ps),
            "attacker_decisions": length_by_id.get(tid, ""),
            "mean_same_exchange_cosine": mean(scores),
            "mean_matched_baseline_delta": mean(deltas) if deltas else "",
            "n_baselined_pairs": len(deltas),
            "mean_defender_next_attacker_cosine": mean(lagged) if lagged else "",
            "n_lagged_pairs": len(lagged),
            "cosine_per_defender_turn_slope": slope if slope is not None else "",
        })
    write(source / "03_trajectory_similarities.csv",
          trajectory_rows, list(trajectory_rows[0]))

    report = [
        "# Sentence-BERT strategy-alignment pilot (RQ1, exploratory)", "",
        f"- Embedding model: `{model_id}`",
        f"- Complete matched events: **{len(output)}**",
        f"- Distinct strategies embedded: {len(texts)}",
        f"- Independent trajectories with matched data: {len(trajectory_rows)}",
        "- Within-exchange cosine measures relatedness, NOT agreement or deception.",
        "- The negative reference uses different trajectories matched on app, configuration and EXACT attacker step.",
        "- Cluster bootstrap intervals below sample trajectories, not individual strategy pairs.",
        "- Missing references are left missing (never fabricated).",
        "",
        "## Trajectory-weighted results", "",
        "| Application | Trajectories | Avg. within-exchange cosine | Avg. delta vs matched reference | Cluster bootstrap 95% interval for delta |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for app in sorted(set(x["app"] for x in trajectory_rows)):
        group = [x for x in trajectory_rows if x["app"] == app]
        observed = mean(x["mean_same_exchange_cosine"] for x in group)
        deltas = [x["mean_matched_baseline_delta"] for x in group
                  if isinstance(x["mean_matched_baseline_delta"], (int, float))]
        delta = mean(deltas) if deltas else None
        ci = interval(deltas, bootstrap, seed)
        ci_string = (f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "not estimable")
        report.append(
            f"| {app} | {len(group)} | {observed:.3f} | "
            f"{delta:.3f}" if delta is not None else
            f"| {app} | {len(group)} | {observed:.3f} | unavailable"
        )
        report[-1] += f" | {ci_string} |"
    report += [
        "", "## Temporal interpretation", "",
        "The by-turn CSV contains sample sizes; later turns include only trajectories "
        "that survived that far. A rising mean does not prove convergence.",
        "Per-trajectory slopes require at least three defender decisions. "
        "The lagged measure is D(t) vs the next attacker decision A(t+1) "
        "and is descriptive rather than causal.",
        "", "## Next steps", "",
        "Audit representative high- and low-similarity pairs manually to verify that "
        "cosine represents strategic commonality rather than repeated endpoint names.",
        "Independently annotate deception and suspicion; do not equate similarity "
        "with either construct.",
        "For RQ5 analyze early-window strategy features against subsequent duration "
        "and account for give-ups, parser errors, and step-cap censoring.",
        "",
    ]
    report_path = source / "03_embedding_report.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"Outputs saved to {source}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="Directory generated by 01_prepare_data.py")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2",
                        help="Sentence embedding model from Hugging Face")
    parser.add_argument("--bootstrap", type=int, default=2000,
                        help="Number of trajectory-cluster bootstrap replicates")
    parser.add_argument("--seed", type=int, default=99)
    args = parser.parse_args()
    if args.bootstrap < 1:
        parser.error("--bootstrap must be >= 1")
    run(args.input, args.model, args.bootstrap, args.seed)
