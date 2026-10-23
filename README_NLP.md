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

Choose **smoke** (1 sample), **pilot** (10 samples), or **manual**.
Smoke and pilot retain their original GPT-5.4-mini / GPT-5.4-nano defaults.
**Menu option 3 is now an interactive manual setup**, with editable models,
app selection, attacker/defender prompts, sample counts, steps, reasoning
efforts, and per-trajectory cost limits. It also enables our NLP strategy
logging by default.

For a strong attacker versus small defender, manual defaults to
`openai/gpt-6-astra-python-curl` (GPT-6 Astra attacker with original
Honeyval curl/Python tools) and `openai/gpt-6-luna` (GPT-6 Luna defender),
with `exploit` / `mislead`. These are the October 2026 flagship and
efficiency models respectively. `openai/gpt-6.1-sol-python-curl` is a
lower-cost alternative attacker.

Example interactive run:

```bash
cd /work/honeyval_project/honeyval
bash scripts/nlp/experiment.sh
# Enter 3, then accept/edit the defaults, and confirm with y.
```

For advanced scripts, the original full CLI passthrough still works:

```bash
bash scripts/nlp/experiment.sh manual --mode run --meta_experiment_type my-run ...
```

Or preview the assembled command **without running any API calls**:

```bash
HONEYVAL_DRY_RUN=1 bash scripts/nlp/experiment.sh
# Choose 3, then fill out the fields.
```

Both interactive manual and direct passthrough use
`HONEYVAL_LOG_STRATEGY=1` by default. To opt out, set
`HONEYVAL_LOG_STRATEGY=0` explicitly.

**GPT-6 support:** The NLP fork adds GPT-6 Astra, GPT-6.1 Sol, and GPT-6
Luna to `src/utils/constants.py` for token-cost accounting and changes
`src/utils/litellm_erb.py` so GPT-6 reasoning requests do not send
unsupported custom `temperature` or `top_p`. Honeyval's original
API-error backoff/retries remain intact. New models may require an updated
LiteLLM installation and API model access; validate one trajectory before
launching a batch. The framework uses Chat Completions with manually
parsed XML tool actions (not OpenAI's native function-calling interface).

**Costs:** The manual defaults limit each attacker trajectory to $5 and each
defender trajectory to $2, not the total experiment. Pricing uses standard
API rates as of October 2026 and is approximate; multiple apps and samples
multiply the number of trajectories. Do not assume an overall spending cap.

To run noninteractively with the original smoke defaults:

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

## NLP RESEARCH EXTENSION — contemporaneous strategies only

**CUSTOM research extension, not upstream Honeyval.** Under the 23 October 2026
protocol, each decision uses the **first completed model generation**; no
extra generation is made to fix a missing strategy. Original API retries
for failed calls remain intact. We extract an optional `<STRATEGY>...</STRATEGY>` summary from that
generation and strip the tag before normal action/HTTP processing.

If the model omits a strategy, our research extension **does not request a
new decision, regenerate the action, or request a retrospective explanation**.
Honeyval's ORIGINAL API-error retries are unchanged (attacker: up to 10 attempts;
defender: up to 5, when the API call fails). The original action or HTTP response
still proceeds normally. We record `strategy=null`,
`strategy_valid=false`, and `strategy_source="missing"`. A malformed or
empty action stays malformed/empty and generates no attacker HTTP request.
The defender only generates an HTTP response if a request actually reaches it.

For successful contemporaneous capture, `strategy_source="contemporaneous"`.
Old audit fields remain for backwards compatibility: `strategy_attempts=1`,
`strategy_retried=false`, and both `strategy_retry_response` and
`strategy_explanation_response` are null in NEW runs. The optional
strategy-first output format is integrated next to the original ACTION and
RESPONSE examples only when strategy logging is enabled.

**Do not mix protocols without distinction.** Earlier pilot datasets used
action-changing complete-output retries or retrospective explanation-only
calls. Those records retain their original strategy provenance and need
separate interpretation. Always save the experiment's Git commit hash.
Strategies are elicited self-reports, not access to hidden model reasoning.

Smoke/pilot via `scripts/nlp/experiment.sh` enables
`HONEYVAL_LOG_STRATEGY=1` automatically. Direct/manual runs must set it
explicitly. Existing Honeyval attacker and honeypot instructions remain
unchanged except for the strategy logging requirement. Our code additions are
marked `NLP RESEARCH EXTENSION`.

## Where the actual model prompts come from

The full prompt visible in an `agent.log` or `http-app.log` is assembled
from several files. Use this map when editing prompts, rather than changing
arbitrary strings in the log.

| Prompt component | Edit/inspect this file | How it is used |
| --- | --- | --- |
| Attacker system instructions, ACTION/TOOL schema, examples, and environment-observation prompt | `src/agents/prompts.py` | `SIMPLE_REACT_SYSTEM_PROMPT`, `SIMPLE_REACT_INITIAL_PROMPT`, and `SIMPLE_REACT_ENVIRONMENT_RESPONSE_PROMPT` |
| Attacker's specific exploitation task and optional honeypot-detection warning | `src/benchmark_prompts.py` | `PENTESTING_PROMPT_EXPLOIT` and `HONEYPOT_DETECTION_PROMPT` (or hide variant) |
| Defender's deception/engagement objective for `--honeypot_additional_instructions mislead` | `src/benchmark_prompts.py` | `HONEYPOT_ADDITIONAL_INSTRUCTIONS_MISLEADING` |
| CLI mapping of `exploit`, `exploit-detect`, `mislead`, etc. | `src/main.py` | Selects which benchmark prompts and models to use |
| Defender's baseline HTTP agent system prompt, OpenAPI and RESPONSE/STATUS/HEADER format | `src/http_apps/http_llm_honeypot.py` | `HOSTED_WEBAPP_SYSTEM_PROMPT` |
| Login/Forum and other benchmark-specific goals and application descriptions | `src/benchmark_apps/` | Benchmark app definitions, including `login.py` and `forum.py` |
| OpenAPI specification for each app | Selected benchmark app's `openapi_config_path` (referenced by its definition under `src/benchmark_apps/`) | Inserted as `<OPENAPI_SPEC>` for attacker and `<OPENAPI_SCHEME>` for defender |
| **Our attacker and defender strategy-first instructions** | **`src/utils/strategy_logging.py`** | `ATTACKER_STRATEGY_INSTRUCTION`, `DEFENDER_STRATEGY_INSTRUCTION` and `add_strategy_instructions()` |
| Point where the attacker system prompt is assembled | `src/agents/simple_react_agent.py` | `SimpleReactAgent._set_system_prompt()` |
| Point where the defender system prompt is assembled | `src/http_apps/http_llm_honeypot.py` | `HttpLLMHoneypot._set_system_prompt()` |

**Why the research instructions appear in the middle now:** with
`HONEYVAL_LOG_STRATEGY=1`, `add_strategy_instructions()` inserts an
example `<STRATEGY>...</STRATEGY>` immediately **before** each relevant
`<ACTION>` or `<RESPONSE>` example in the assembled system prompt. It
also adds concise role-specific instructions immediately alongside those
formats. The original upstream prompt strings are not edited. This is a
strategy-first *output convention*; it does not expose hidden reasoning.
The model still generates one complete response, Honeyval extracts the
summary, then processes the ACTION or RESPONSE normally.

The actual assembled attacker prompt is shown in `logs/agent.log`, and
the defender prompt is shown in `logs/http-app.log`. The agent's later
`Action-parsing response (STRATEGY removed if present)` debug entry is
**not** the original model generation. For the actual first generation,
inspect `strategy_initial_response` in `agent-metadata.jsonl` or
`http-app-metadata.jsonl`.

**Experimental discipline:** freeze the prompt and save the Git commit
SHA for each batch. If changing only the research instruction, edit the
two role-specific constants in `src/utils/strategy_logging.py`; don't
change both them and the deception/attack objectives in the same comparison.

## Candidate RQ5 — long versus short interactions

**Working question (not yet selected):** How do attackers' and defenders'
expressed strategies differ between short and sustained interactions?
Are specific defender linguistic strategies associated with longer attacker
engagement?

Possible trajectory-level measurements: number of *executed attacker
actions*, number of *defender responses*, time to termination, and
termination reason (refusal, give-up, success, error, or max-step censoring).
Potential text features include manually validated tactic labels,
expressed uncertainty, semantic similarity and turn-to-turn embedding
changes. Prefer sentence-embedding models rather than treating raw BERT
token embeddings as ready-made sentence similarity measures.

**Avoid length confounds:** compare strategies within equivalent early
windows (for example the first two valid exchanges), not all text pooled
across a long versus short trajectory; longer runs mechanically offer more
opportunities for deception and linguistic change. Stratify by app, attacker
model, defender model, and outcome. A 6-step maximum truncates trajectories,
so reaching that limit is *right-censoring*, not evidence that an interaction
would naturally have ended at six steps. Refusal/technical failure are not
evidence of successful deception. Associations are not causal effects.

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
