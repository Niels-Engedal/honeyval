# Honeyval on UCloud

Our fork of [Google Research Honeyval](https://github.com/google-research/honeyval) logs attacker and defender interactions for the NLP project. It uses direct OpenAI API access; **Bifrost is not required**. The original README contains the framework's full CLI documentation.

**Verified (22 October 2026):** the strategy-enabled `nlp-strategy-smoke-2` smoke run completed with six attacker decisions and five defender decisions, all with recorded strategies. Four attacker decisions and one defender decision required one correction generation. This verifies one pilot trajectory, not reliability across many runs.

## Tomorrow: restart the existing UCloud VM and continue

1. Start the **same VM** from UCloud and reconnect with **VS Code Remote SSH** (use its UCloud Access / SSH connection details). Starting a different, fresh VM may require reinstalling Miniconda, Docker, and Docker images.
2. Open a VS Code terminal and run:

```bash
cd /work/honeyval_project/honeyval
git switch feature/interaction-logging
git pull --ff-only
source scripts/nlp/setup.sh
```

3. Confirm the terminal reports `Conda: honeyval`, `OpenAI API key: loaded`, and `Python Docker connection: OK`. To verify the saved pilot data:

```bash
find results/nlp-strategy-smoke-2 -name '*metadata.jsonl' -exec wc -l {} +
```

4. Before another experiment check `pgrep -af '[p]ython.*src/main.py'` and `docker ps`. Old Honeyval containers may survive reconnects or interrupted runs. Do not remove containers used by an active run. For long experiments use `tmux` inside the VS Code SSH terminal so disconnecting SSH does not end the shell session; tmux cannot survive rebooting the VM.
5. Run `bash scripts/nlp/experiment.sh`, choose smoke or pilot, and **use a fresh experiment name**. Each API run incurs costs.

**Persistence:** this checkout is under `/work/honeyval_project/honeyval`, so Honeyval writes outputs to `/work/honeyval_project/honeyval/results/`. Those outputs persist when the same persistent UCloud Member Files `/work` mount is reattached to another job. Verify the mount and files after reconnecting; do not assume VM-local `/home/ucloud` survives replacement. The private key lives under `/work/honeyval_project/.secrets/`.

**Restart checklist (quick copy/paste):**

```bash
cd /work/honeyval_project/honeyval
git switch feature/interaction-logging
git pull --ff-only
source scripts/nlp/setup.sh
docker ps
bash scripts/nlp/experiment.sh
```

The experiment script's smoke/pilot modes enable custom NLP strategy logging. Choose a **new experiment name** and verify strategy coverage using the inspection command near the end of this README. Do **not** delete old Docker containers if a Honeyval process is still running. Your existing `nlp-strategy-smoke-2` data remain under `results/`.

## Start here (existing UCloud environment)

UCloud may open a new shell at `/work`, losing the active Conda environment and exported variables. Shell command history can still be present. Use **source** so setup changes the current shell:

```bash
cd /work/honeyval_project/honeyval
git pull --ff-only
source scripts/nlp/setup.sh
```

The setup script:
- Activates the existing `honeyval` Conda environment (creates and installs it if absent).
- Asks for an OpenAI API key **only if the private file is missing**. Stores it in `/work/honeyval_project/.secrets/honeyval.env` with permission 600, outside Git.
- Loads the key into the current terminal without displaying it.
- Checks Docker access and warns about leftover Honeyval containers, without deleting them.
- Returns to the repository root.

Each collaborator must use a private UCloud Unix account/workspace or set `HONEYVAL_ENV_FILE` to their own inaccessible-to-others path. The default works for our existing `/work/honeyval_project` layout. Docker group access is powerful: use a dedicated VM.

**Fresh VM:** first install Docker and Miniconda as described in the [upstream README](README.md), then clone this fork and select `feature/interaction-logging`:

```bash
mkdir -p /work/honeyval_project && cd /work/honeyval_project
git clone https://github.com/Niels-Engedal/honeyval.git
cd honeyval
git switch --track origin/feature/interaction-logging
source scripts/nlp/setup.sh
```

If Docker group changes are needed, `newgrp docker` starts another shell. Run `source scripts/nlp/setup.sh` again afterward. For environments where Docker image builds time out on PyPI, see upstream `src/utils/constants.py` for Dockerfile definitions; building those image definitions with `docker build --network=host` can help. The two needed images are `fastapi-webapp-base` and `sandbox`.

## Run an experiment

```bash
bash scripts/nlp/experiment.sh
```

Choose **smoke** (1 sample), **pilot** (10 samples), or **manual**. The script asks for a run name, sample count, and maximum attacker steps, then launches Honeyval and summarizes results. It assigns a timestamped name by default to avoid overwriting earlier runs. Docker image builds and API requests may take time; the progress bar only updates when a sample finishes.

To run noninteractively with the smoke defaults:

```bash
bash scripts/nlp/experiment.sh smoke
```

For complete control, run the ordinary CLI via our private-env launcher. Example, changing the model, sample count and instruction type:

```bash
bash scripts/nlp/run_honeyval.sh \
  --mode run \
  --meta_experiment_type nlp-my-experiment \
  --benchmark_tasks agent-vs-http-app \
  --benchmark_apps Login \
  --pentest_model openai/gpt-5.4-mini-python-curl \
  --honeypot_type llm \
  --honeypot_model openai/gpt-5.4-nano \
  --pentesting_prompt exploit-detect \
  --n_samples 3 \
  --max_workers 1 \
  --pentest_max_steps 8 \
  --pentest_reasoning_effort low \
  --honeypot_reasoning_effort low \
  --pentest_cost_limit 1 \
  --honeypot_cost_limit 1
```

The launcher only sources the private key and invokes Honeyval's `src/main.py`. No separate proxy/server is installed.

## Results and troubleshooting

Results are under `results/<experiment-name>/<configuration>/<app>/<sample>/agent-vs-http-app/` in the repository on `/work`. Most useful files:

- `logs/agent.log` — attacker actions and observations
- `logs/http-app.log` — honeypot HTTP/backend activity
- `metadata-logs/agent-metadata.jsonl` — structured attacker events
- `metadata-logs/http-app-metadata.jsonl` — structured defender events (including our `raw_response` field)

To find logs: `find results/<experiment-name> -name '*.log'`. A zero-error task and complete JSONL files demonstrate a completed run, **not** a successful attack. Generated response text is not hidden model reasoning. Treat logs as potentially sensitive and never commit them or API keys to Git.

**After interruption:** inspect `docker ps`. An interrupted experiment can leave containers and firewall rules behind. Do not remove containers belonging to an active experiment; inspect owners/processes first. On the previous UCloud VM, several old `agent-sandbox-*` and `honeypot-Login-*` containers were found. Firewall restrictions require `sudo -n /sbin/iptables -S DOCKER-USER` and confirmation there are no `iptables insert failed` warnings. Don't use the attacker sandbox with unknown/untrusted agents unless isolation has been checked.

```bash
grep -R 'Task finished. Number of errors:' results/<experiment-name> --include='task.log'
find results/<experiment-name> -name '*.jsonl' -exec wc -l {} +
grep -R 'iptables insert failed' results/<experiment-name> --include='*.log' || true
```

Project changes live on `feature/interaction-logging` until the draft PR is validated. Record the Git commit hash and experimental parameters when collecting data for analysis.

## NLP RESEARCH EXTENSION — fixed decisions and strategy provenance

This section documents CUSTOM research additions, NOT upstream Honeyval.
The guided smoke/pilot launcher enables HONEYVAL_LOG_STRATEGY=1. Manual and
direct runs must set that environment variable explicitly. Honeyval's original
attacker and defender objectives, including mislead when selected, are retained.

**Protocol updated 23 October 2026:** Our earlier research-only retry
regenerated a complete model response and sometimes CHANGED the chosen action.
Therefore, older pilot data are subject to an action-regeneration confound.

**Current procedure:** The FIRST model generation is ALWAYS the fixed action
or HTTP response (after stripping its STRATEGY tag). If a strategy is missing,
one optional second model call only EXPLAINS that fixed decision. Its output
is never executed, returned as an HTTP response, or added to persistent
participant conversation histories. Failure to obtain an explanation never
replaces or prevents the first decision.

strategy_source is contemporaneous, retrospective, or missing. Records
also retain strategy_valid, strategy_attempts, strategy_retried (legacy name),
strategy_initial_response, strategy_retry_response (legacy name), and
strategy_explanation_response. The latter two capture only explanations in
new runs. Keep protocol version or Git SHA with each experiment; do not pool
old and new runs uncritically. Retrospective statements are elicited
self-reports, NOT observations of hidden model reasoning.

All implementation changes are marked NLP RESEARCH EXTENSION in
src/utils/strategy_logging.py, src/agents/simple_react_agent.py, and
src/http_apps/http_llm_honeypot.py. No sandbox networking code changed.
## Inspect strategy completeness after any run

Change the experiment name below, then run from the repository root:

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path("results/nlp-strategy-smoke-2")  # change to your run name
for filename, role in [("agent-metadata.jsonl", "ATTACKER"),
                       ("http-app-metadata.jsonl", "DEFENDER")]:
    records = [json.loads(line) for file in root.rglob(filename)
               for line in file.read_text().splitlines() if line.strip()]
    decisions = [r for r in records if r.get("event") not in
                 {"START", "END", "ERROR", "RATE_LIMIT_ERROR"}]
    valid = sum(bool(r.get("strategy_valid")) for r in decisions)
    retried = sum(bool(r.get("strategy_retried")) for r in decisions)
    print(f"{role}: {valid}/{len(decisions)} strategies; {retried} retried")
    for i, item in enumerate(decisions, 1):
        if not item.get("strategy_valid"):
            print(f"  MISSING: decision {i}, event={item.get('event')}")
PY
```

Observed in `nlp-strategy-smoke-2`: **attacker 6/6 (4 retries), defender 5/5 (1 retry)**. This means strategy capture worked in this test. It does **not** prove that the summaries reflect private internal reasoning or that every future run will have 100% coverage. This OLD experiment used action-regenerating retries, which sometimes changed the first decision. New runs preserve first-pass decisions.

**Tests:** the optional unit tests are in `tests/test_strategy_logging.py`. `pytest` is **not preinstalled** in our current Conda environment; running `python -m pytest` without installing it will fail with `No module named pytest`. If wanted, install it with `python -m pip install pytest` and then run `python -m pytest tests/test_strategy_logging.py -q`. This is separate from running a smoke experiment.
