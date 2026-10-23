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

Strategies are model-reported, not internal reasoning. This report does not compute embeddings, claim deceptive intent from HTTP 400/401, or infer causality. Experiments with different logging protocols should be analyzed separately or have their protocol tracked explicitly. These scripts are independent research extensions, not upstream Google Honeyval modules.
