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

## NLP RESEARCH EXTENSION: model-generated strategy summaries (enabled by guided runner)

The guided experiment launcher **always enables** `HONEYVAL_LOG_STRATEGY=1`. For direct use of `run_honeyval.sh`, strategy collection is explicitly enabled with that environment variable. The existing Honeyval prompts are retained and augmented with a research-only output requirement. Both LLM prompts request a **1–3 sentence, high-level strategy statement** enclosed in `<STRATEGY>...</STRATEGY>` before each normal action or HTTP response. Honeyval extracts the statement into the `strategy` field of the appropriate JSONL event and strips it from the tool/HTTP output and future model conversation history. When a strategy is missing, one additional generation is requested before executing any action or returning any HTTP response; records still missing a strategy are flagged.

This is an **elicited explanation of the model's decision**, not hidden chain-of-thought or an independent readout of internal reasoning. The prompt changes model behavior and token consumption; analyses comparing prompted to unprompted models must treat this as an intervention.

To make a run with strategy logging from the unmodified command-line launcher, prepend `HONEYVAL_LOG_STRATEGY=1`:

```bash
HONEYVAL_LOG_STRATEGY=1 bash scripts/nlp/run_honeyval.sh --mode run [your other arguments here]
```

The `agent-metadata.jsonl` and `http-app-metadata.jsonl` records have timestamps, inputs/outputs, token fields, and a `strategy` statement when successfully elicited. Align events by sample directory, chronological timestamps, and request content; **do not assume attacker and defender event counts are equal**, since an attacker action can produce zero or multiple HTTP requests. Check the rate of missing strategy fields before scaling up.

### NLP RESEARCH EXTENSION — NOT UPSTREAM HONEYVAL

**All** strategy prompting, retry-on-missing, and `strategy_*` fields are
custom research modifications. See the `NLP RESEARCH EXTENSION` comments in
`src/utils/strategy_logging.py`, `src/agents/simple_react_agent.py` and
`src/http_apps/http_llm_honeypot.py`. The original honeypot instructions
and HTTP schema are not replaced.

Every model-generated decision records `strategy`, `strategy_valid`,
`strategy_attempts` (1 or 2), `strategy_retried`, and both
`strategy_initial_response` and `strategy_retry_response` for an audit trail.
The retry adds only a temporary private correction prompt to the model's
current messages and is never forwarded to the opposing model. Token totals
include both model generations. A correction may change an action/response,
which is a research intervention: compare the initial and final outputs in
analyses. Exclude records with `strategy_valid=false` from strategy NLP.
Lifecycle events START/END are not model decisions.

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

Observed in `nlp-strategy-smoke-2`: **attacker 6/6 (4 retries), defender 5/5 (1 retry)**. This means strategy capture worked in this test. It does **not** prove that the summaries reflect private internal reasoning or that every future run will have 100% coverage. A retry can alter the resulting action; compare the original and corrected responses when interpreting behaviour.

**Tests:** the optional unit tests are in `tests/test_strategy_logging.py`; the environment may not include `pytest`. If necessary, install it with `python -m pip install pytest` and run `python -m pytest tests/test_strategy_logging.py -q`. This is separate from running a smoke experiment.
