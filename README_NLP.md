# NLP Masters — reproducible Honeyval setup (UCloud)

This guide supplements the [upstream Honeyval README](README.md). We use **the upstream Python/Conda/Docker workflow and direct OpenAI API access**, not a separate Bifrost deployment. Our fork adds research logging and a minimal model-prefix compatibility fix.

> **Status:** Docker and FastAPI frontend startup were observed working on UCloud. The previous attacker API attempt returned *invalid model ID*. The prefix fix has been committed, **but an end-to-end successful run has not yet been verified**. The commands below are reproducible procedures, not a claim that the smoke test passed.

## Architecture and Bifrost decision

- **LiteLLM** is the Python library Honeyval calls to access model APIs.
- **Bifrost** is an optional OpenAI-compatible gateway/proxy that can route requests through another service. It is **not** prescribed in Honeyval's upstream README.
- **Default for this project:** set `OPENAI_API_KEY`, leave `BIFROST_URL` and `BIFROST_KEY` **unset**, and call `python src/main.py` (or the wrapper below, which invokes the same program).
- In the current upstream LiteLLM wrapper, `openai/` was prepended to already-prefixed CLI model IDs; this fork normalizes the prefix. We don't install or maintain a separate proxy for a small experiment.

## Requirements

- UCloud Ubuntu 24.04 with persistent `/work` storage
- Docker daemon and permission to use it; `docker ps` must work in the **same shell** that launches Honeyval
- Miniconda, Python 3.12 from `env.yaml`
- A funded OpenAI API key; usage is billable
- A private per-user workspace (especially for API secrets and attack logs)

## One-time setup on a fresh UCloud VM

These commands assume an x86_64 Linux VM, `/work/honeyval_project`, and Miniconda installed in `/home/ucloud/miniconda3`. Adjust if different.

```bash
mkdir -p /work/honeyval_project
cd /work/honeyval_project

# Clone our fork directly. Use upstream as a secondary remote.
git clone https://github.com/Niels-Engedal/honeyval.git
cd honeyval
git remote add upstream https://github.com/google-research/honeyval.git
git fetch origin
git switch --track origin/feature/interaction-logging

# If conda is not yet installed, first follow the upstream README.
source /home/ucloud/miniconda3/etc/profile.d/conda.sh
conda env create -f env.yaml
conda activate honeyval
python -m pip install 'litellm[proxy]'
python -m pip install -e .
```

Our `env.yaml` pins `click=8.1.8` because the upstream Typer/code generator combination failed with a newer Click on UCloud.

Docker setup is host-specific. Follow the [official Docker Engine Ubuntu installation guide](https://docs.docker.com/engine/install/ubuntu/) if needed. If your account is not in the `docker` group, request appropriate access, then use `newgrp docker` to refresh group membership. Note that Docker-group access grants privileged host capabilities: use a dedicated VM, not a shared untrusted machine.

**Do not put a key in code, Git, command-line arguments, or `~/.bashrc`.**

## One-time private credential file

Run in your **own** UCloud workspace; don't use a shared Unix login for multiple collaborators:

```bash
mkdir -p /work/honeyval_project/.secrets
chmod 700 /work/honeyval_project/.secrets
umask 077
read -rsp 'OpenAI API key: ' OPENAI_API_KEY
echo
printf 'OPENAI_API_KEY=%q\n' "$OPENAI_API_KEY" > /work/honeyval_project/.secrets/honeyval.env
unset OPENAI_API_KEY
chmod 600 /work/honeyval_project/.secrets/honeyval.env
```

The file lives **outside the Git repository**. File permissions protect it from other nonprivileged Unix users, not from root, the same Unix account, or storage administrators. Each collaborator should use their **own API key** and a private credentials directory. An alternative is a cloud secrets manager.

To load credentials into one interactive session:

```bash
set -a
source /work/honeyval_project/.secrets/honeyval.env
set +a
python -c "import os; print('API key configured:', bool(os.getenv('OPENAI_API_KEY')))"
```

This session-only loading is optional if you use the launcher script below.

## Normal session startup / after a new UCloud terminal

```bash
cd /work/honeyval_project/honeyval
source /home/ucloud/miniconda3/etc/profile.d/conda.sh
conda activate honeyval

# Refresh Git branch:
git switch feature/interaction-logging
git pull --ff-only

# Check Docker for this very shell (newgrp docker if needed):
id -nG
docker ps
python - <<'PY'
import docker
client = docker.from_env()
print('Python Docker API:', client.ping())
client.close()
PY
```

Your current terminal may reopen at `/work` with no exported key. That does **not** delete the file on disk.

## Simple launcher that loads the private key

The following script is tracked in our fork: `scripts/nlp/run_honeyval.sh`. It does **exactly** what activating Python and running `src/main.py` does, plus loading the key from the external file. From the repository root:

```bash
bash scripts/nlp/run_honeyval.sh --help
```

Override the default credential file via `HONEYVAL_ENV_FILE=/path/to/private.env` when needed. The launcher never prints the credential.

## Preflight before paying for an experiment

```bash
cd /work/honeyval_project/honeyval
docker ps
docker image ls fastapi-webapp-base
docker image ls sandbox

# Check that firewall rules required for the attacker sandbox can be inspected:
sudo -n /sbin/iptables -S DOCKER-USER
```

If your sandbox is missing and normal Docker builds time out when pip downloads dependencies on UCloud, you can build *the same upstream Dockerfile* using host networking **during build only**:

```bash
docker build --network=host -t sandbox - <<'EOF'
FROM python:3.12.11-alpine3.21
WORKDIR /sandbox
RUN apk update && apk add curl bash
RUN pip3 install requests
EOF
```

The frontend base image is defined in `src/utils/constants.py`; similarly:

```bash
docker build --network=host -t fastapi-webapp-base - <<'EOF'
FROM python:3.12.11-alpine3.21
WORKDIR /app
RUN pip install fastapi uvicorn httpx
EOF
```

**Important:** The attacker sandbox applies network restrictions through `iptables`. Before allowing untrusted agent-generated commands, verify that no `iptables insert failed` warnings appear in its log and the rules actually restrict sandbox egress. The current implementation logs some firewall failures as warnings rather than aborting; do not assume isolation based solely on a zero-error task summary.

### Cheap one-call model check (no Docker experiment)

Use the official OpenAI SDK or LiteLLM to verify model availability before running Honeyval. This test uses two small paid requests and reports only success/errors, never the key.

```bash
set -a; source /work/honeyval_project/.secrets/honeyval.env; set +a
python - <<'PY'
from openai import OpenAI
client = OpenAI()
for name in ('gpt-5.4-mini', 'gpt-5.4-nano'):
    try:
        r = client.chat.completions.create(
            model=name, messages=[{'role': 'user', 'content': 'Reply OK'}],
            max_completion_tokens=128,
        )
        print(name, 'OK', r.id)
    except Exception as e:
        print(name, 'FAILED:', type(e).__name__, str(e)[:300])
PY
```

A successful direct SDK call proves the key/model pairing works; it does not yet prove the full Honeyval run works.

## Smoke test — one Login simulation, maximum six attacker steps

Always run from repository root; `Login` is **case-sensitive**. This example uses **one sample and one worker**, two OpenAI models, low reasoning effort, and nominal cost limits.

```bash
bash scripts/nlp/run_honeyval.sh \
  --mode run \
  --meta_experiment_type nlp-smoke-v4 \
  --benchmark_tasks agent-vs-http-app \
  --benchmark_apps Login \
  --pentest_model openai/gpt-5.4-mini-python-curl \
  --honeypot_type llm \
  --honeypot_model openai/gpt-5.4-nano \
  --pentesting_prompt exploit \
  --n_samples 1 \
  --max_workers 1 \
  --pentest_max_steps 6 \
  --pentest_timeout 300 \
  --pentest_reasoning_effort low \
  --honeypot_reasoning_effort low \
  --pentest_cost_limit 1 \
  --honeypot_cost_limit 1
```

The application can still incur some costs (and model calls can fail) even with cost limits; `--force` reruns and may replace earlier results, so **do not add it unless deliberately rerunning**.

### Observe progress (in a second terminal)

The progress bar stays at `0/1` until the entire subtask completes. Watch disk logs:

```bash
find results/nlp-smoke-v4 -name '*.log'
tail -f results/nlp-smoke-v4/*/Login/0/agent-vs-http-app/logs/agent.log
tail -n 35 results/nlp-smoke-v4/*/Login/0/agent-vs-http-app/task.log
```

A `litellm.BadRequestError: ... invalid model ID` indicates provider/model configuration; it is **not** a Docker build hang. Other causes can be inspected in `http-app.log`, `agent.log`, and Docker logs.

After the run:

```bash
grep -R 'Task finished. Number of errors:' results/nlp-smoke-v4 --include='task.log'
find results/nlp-smoke-v4 -name '*.jsonl' -exec wc -l {} +
grep -R 'iptables insert failed' results/nlp-smoke-v4 --include='*.log' || true
```

The desired outcome is `Number of errors: 0` and nonempty JSONL records for both the agent and HTTP-app (but this is not by itself proof of effective firewall rules).

## Actual pilot run — 10 Login trajectories

**Only after a successful smoke test and verified network isolation**, run a small pilot, keeping one worker to simplify debugging and avoid unexpectedly high API costs:

```bash
bash scripts/nlp/run_honeyval.sh \
  --mode run \
  --meta_experiment_type nlp-pilot-login \
  --benchmark_tasks agent-vs-http-app \
  --benchmark_apps Login \
  --pentest_model openai/gpt-5.4-mini-python-curl \
  --honeypot_type llm \
  --honeypot_model openai/gpt-5.4-nano \
  --pentesting_prompt exploit \
  --n_samples 10 \
  --max_workers 1 \
  --pentest_max_steps 6 \
  --pentest_timeout 300 \
  --pentest_reasoning_effort low \
  --honeypot_reasoning_effort low \
  --pentest_cost_limit 1 \
  --honeypot_cost_limit 1
```

This is an initial pilot, **not** a statistical sample-size justification. Freeze the model and prompt configuration, record git commit IDs, random seeds where available, costs, and failure rates before scaling to the NLP study.

## What we collect

Files live under `results/<meta_experiment_type>/<model-combination>/Login/<sample>/agent-vs-http-app/`.

- `logs/agent.log`: attacker-side execution trace
- `metadata-logs/agent-metadata.jsonl`: structured attacker-side events
- `logs/http-app.log`: backend trace (may contain sensitive synthetic secrets and prompts)
- `metadata-logs/http-app-metadata.jsonl`: structured defender request/response events; our fork adds `raw_response` with the **full generated answer** returned by the LLM

**Research caveat:** `raw_response` is model *output text*, not necessarily access to hidden private chain-of-thought. Treat the observable text, actions, and timestamps as the analyzable data. Never publish API keys, real user identifiers, or accidentally captured private data from logs.

## Reproducibility checklist

- Record the output of `git rev-parse HEAD` and `conda list --explicit` (privately)
- Keep `env.yaml`, model IDs, app IDs, prompts, limits, and evaluation settings fixed
- Preserve original JSONL and logs, but do not commit them to Git; the fork ignores `results/`
- Track errors and rejected API calls; `0/1` on the progress bar is not sufficient evidence of a freeze
- If setup changes, document what changed and why, rather than modifying upstream mechanisms preemptively

## Upstream synchronization

Our fork has `origin` and `upstream` remotes. Work on `feature/interaction-logging` during testing. Do not merge the draft PR into `main` before validation.
