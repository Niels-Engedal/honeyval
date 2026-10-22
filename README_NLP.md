# Honeyval on UCloud

Our fork of [Google Research Honeyval](https://github.com/google-research/honeyval) logs attacker and defender interactions for the NLP project. It uses direct OpenAI API access; **Bifrost is not required**. The original README contains the framework's full CLI documentation.

**Working baseline (22 October 2026):** the `Login` smoke test completed with zero task errors, six attacker JSONL events and six defender JSONL events. The attacker did not succeed (which is fine for a smoke test). A 10-sample pilot was started but its final outcome wasn't provided.

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

Results are under `results/<experiment-name>/<configuration>/<app>/<sample>/agent-vs-http-app/`. Most useful files:

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
