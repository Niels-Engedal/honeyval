# Honeyval NLP exploratory analysis (standalone)

These are independently tested, standard-library scripts. They do **not** change Honeyval, generate requests, or run agents. They can read an experiment `results/<experiment>` directory or an archived ZIP of that directory.

## On UCloud

From the Honeyval repository root after pulling `feature/interaction-logging`:

```bash
python nlp_research_scripts/01_prepare_data.py \
  --input results/nlp-luna-vs-luna-1 \
  --output analysis_outputs/luna-test
python nlp_research_scripts/02_explore_data.py --input analysis_outputs/luna-test
```

For a new pilot replace both input/output names. To process a ZIP, pass its exact path to `--input` in script 01.

The output contains `decisions.csv` (every model generation), `paired_exchanges.csv` (defender LLM calls paired with their containing attacker tool action, allowing non-paired attacker events), `trajectories.csv`, `warnings.txt`, and `pilot_report.md`.

**Hybrid honeypot:** the FastAPI frontend handles some requests without invoking the defender LLM; therefore attacker and defender event counts legitimately differ. Pairing is by task-specific model-call timestamps, **not** by row index. Always inspect `warnings.txt`, especially if an action could make multiple HTTP requests or metadata is incomplete.

## Diagnose action formatting (script 02)

The descriptive report includes an **attacker parsing-error diagnostic** and
min/median/max trajectory lengths separately for Login and Forum. An attacker
`PARSING ERROR` means Honeyval could not parse the generated ACTION/TOOL
markup, even if the model emitted a valid STRATEGY. Treat those events as
instrumentation/format failures rather than completed attack attempts.

## RQ1 exploratory sentence embeddings (script 03)

First generate the CSVs using script 01. Install the analysis-only dependency
if it is not already available:

```bash
python -c "import sentence_transformers, numpy" || python -m pip install sentence-transformers
python nlp_research_scripts/03_embed_strategies.py --input analysis_outputs/luna-pilot-v2
```

Defaults to `sentence-transformers/all-MiniLM-L6-v2`, which embeds elicited
English strategy summaries. The script generates
`03_pair_similarities.csv`, `03_similarity_by_turn.csv`,
`03_trajectory_similarities.csv`, and `03_embedding_report.md`.

The within-exchange cosine compares paired attacker/defender strategies. The
negative reference compares attacker strategies to defender strategies from
**other trajectories** of the same application, configuration, and exact
attacker step. A second, lagged metric compares defender strategy at an
exchange with the next attacker decision's strategy. The report provides
descriptive trajectory-weighted means and trajectory-cluster bootstrap
intervals when sufficient reference data exist. **Cosine similarity is
semantic relatedness, not agreement, suspicion, deception, or causation.**
Later steps have survivorship bias and should not be treated as independent
samples or direct proof of convergence.

Strategies are model-reported, not internal reasoning. This report does not compute embeddings, claim deceptive intent from HTTP 400/401, or infer causality. Experiments with different logging protocols should be analyzed separately or have their protocol tracked explicitly. These scripts are independent research extensions, not upstream Google Honeyval modules.
