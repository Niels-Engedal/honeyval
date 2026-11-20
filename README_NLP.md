# Honeyval NLP fork

Our fork of [Google Research Honeyval](https://github.com/google-research/honeyval) for the NLP project. It runs on a UCloud VM, calls the APIs directly (no Bifrost) and logs a short strategy statement with every attacker and defender decision. The upstream [README.md](README.md) documents the full CLI.

## 1. Set up UCloud

UCloud keeps `/work` between jobs but wipes `/home/ucloud`. Code, results and keys live under `/work/honeyval_project`; Miniconda, Docker and the Conda env must be reinstalled on a new VM. Restart the same VM when you can.

Keys go in `/work/honeyval_project/.secrets/honeyval.env` (never committed to git):

```bash
OPENAI_API_KEY=...
NEARAI_API_KEY=...
```

**Fresh VM only** (run once):

```bash
# Miniconda, where setup.sh expects it (use the aarch64 installer if `uname -m` says so)
cd /tmp
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p /home/ucloud/miniconda3
source /home/ucloud/miniconda3/etc/profile.d/conda.sh
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Docker and tmux
sudo apt-get update
sudo apt-get install -y docker.io tmux
sudo systemctl enable --now docker
sudo usermod -aG docker ucloud
```

Then open a new terminal or reconnect, so Docker works without `sudo` (`docker ps`). A tmux session started before this won't have Docker access; start a new one or run `newgrp docker`.

If the repo isn't on `/work` yet:

```bash
mkdir -p /work/honeyval_project && cd /work/honeyval_project
git clone https://github.com/Niels-Engedal/honeyval.git
```

**Every session:**

```bash
tmux new -s honeyval              # or: tmux attach -t honeyval
cd /work/honeyval_project/honeyval
git pull --ff-only                # main must track origin/main: git branch -u origin/main main
source scripts/nlp/setup.sh       # first time: answer y to create the Conda env
```

`setup.sh` activates the `honeyval` env, loads the keys without printing them and checks Docker. Continue once it prints `Python Docker connection: OK`. Detach from tmux with `Ctrl-b d`; a run survives SSH disconnects but not a VM reboot.

## 2. Run an experiment

```bash
bash scripts/nlp/experiment.sh    # choose 3) Manual setup
```

The manual menu asks for each setting and shows the planned number of trajectories before starting. Defaults: attacker `nearai/deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated-python-curl`, defender `openai/gpt-6-luna`. Typical answers:

| Question | Default / example |
| --- | --- |
| Experiment name | a new name per run, e.g. `nlp-dsabl-vs-luna-20261119` |
| Benchmark apps | `Calculator CreditCardService Login Recipes`: one app per goal type (command injection, SQL injection, admin password overwrite, local storage exfiltration). `all` selects all 16. |
| Attacker prompt | `exploit-detect` |
| Defender instructions | `vulnerable`; `vulnerable mislead` runs both, each as its own experiment, one after the other |
| Samples per app | `3` |
| Maximum attacker steps | `50`, the upstream default and the iteration cap the Honeyval paper used for its ReAct agent |
| Parallel workers | `3` |
| Honeypot rate limit | `10` requests/minute per honeypot; `-1` turns it off. Upstream default is 50. |

The paper's ~80 "requests per interaction" counts HTTP requests, not attacker steps. One step can send many requests through a script: v2 averaged about 6.5 defender calls per step.

To preview the commands without running anything: `HONEYVAL_DRY_RUN=1 bash scripts/nlp/experiment.sh`. For full control, pass CLI flags straight through: `bash scripts/nlp/experiment.sh manual --mode run --meta_experiment_type ...`.

**Run time and limits.** The defender keeps the whole session history in its prompt (upstream design), so its tokens per call grow during a trajectory and the total grows roughly with the square of the step cap. Throughput is capped by the OpenAI tokens-per-minute limit (2M/min for Luna on our account), not by worker count. Above about 6 workers, calls fail and the attacker sees HTTP 500s or timeouts. Don't run anything else on the same OpenAI account during a run. Cost limits apply per trajectory; there is no cap for the whole batch.

**Honeypot rate limit.** Above the limit the honeypot answers HTTP 429 without calling the defender LLM, like a rate-limited real service. Because each request waits for Luna, a trajectory peaked at about 20 requests/minute in v2. At 50/min the limit never fired; at 10/min it would have cut roughly 10–25% of defender calls in a replay of v2 traffic (Compiler barely changes). It's a setting of the experiment: report it, and keep it the same across conditions you compare.

**Before starting, check nothing else is running:**

```bash
pgrep -af '[p]ython.*src/main.py'
docker ps
```

Concurrent runs need different `--starting_port` values.

**After a stopped or crashed run** (only when nothing is running), remove leftover containers and check for stale firewall rules:

```bash
docker ps -aq --filter name=agent-sandbox- | xargs -r docker rm -f
docker ps -aq --filter name=honeypot- | xargs -r docker rm -f
bash scripts/inspect_docker_networking_rules.sh    # read-only; lists [stale] rules to delete with sudo iptables -D
```

A restarted run reruns unfinished trajectories from step 0.

## 3. Results

```
results/<experiment>/<attacker>-<prompt>-<defender>-<condition>/<App>/<sample>/agent-vs-http-app/
  task.log                               # contains "Task finished" when done
  logs/agent.log, logs/http-app.log      # attacker and defender logs, including the full prompts
  metadata-logs/agent-metadata.jsonl     # one record per attacker decision
  metadata-logs/http-app-metadata.jsonl  # one record per defender response
```

The progress bar counts finished trajectories in the current condition, so it stays at 0% for a long time. To check progress:

```bash
grep -rl 'Task finished' results/<experiment> --include=task.log | wc -l
find results/<experiment> -name agent-metadata.jsonl -exec wc -l {} +
```

Record the Git commit hash with every dataset. Logs may contain sensitive content; never commit them.

**Metrics.** When a batch finishes, the launcher runs preprocessing on its own and writes the analysis tables and metrics to `results/nlp_analysis/<experiment>/`. If that step fails, it prints a warning and the command to rerun by hand; the collected data is never touched. It won't run if you stop the batch with Ctrl-C. To run it yourself:

```bash
python scripts/nlp/analysis_scripts/01_preproc.py \
  --results results/<experiment> --output results/nlp_analysis/<experiment> --max-steps 50
```

Unfinished trajectories are skipped unless you pass `--include-unfinished`. Besides the analysis tables, it writes `interaction_metrics.csv` (one row per trajectory) and `interaction_metrics_summary.csv` (one row per condition). The main columns:

| Metric | Meaning |
| --- | --- |
| `n_defender_requests` | Interaction length as in the paper: HTTP requests the honeypot received, rate-limited ones included |
| `end_reason` | `success`, `giveup`, `step_cap` (needs `--max-steps`) or `no_terminal_action` |
| `honeypot_detected_upstream` / `_any` | Honeyval's detection check (non-tool steps, STRATEGY stripped) and a strict one that checks every attacker output in full |
| `cost_advantage_ratio_of_totals` | Attacker cost ÷ defender cost per condition, as in the paper. Costs are recomputed from the token logs. |
| `share_defender_calls_from_python` | How much of the defender load comes from attacker scripts |
| `attacker_strategy_coverage_after_step5` | Catches strategies dying out later in a trajectory |
| `n_defender_failed_llm_calls`, `n_defender_cost_limited`, `n_defender_rate_limited` | Requests that didn't get a normal defender answer. Failed calls only appear in `http-app.log`, so Honeyval's own interaction length leaves them out. |

The script prints a warning when failed calls, cost-limit hits, task errors or low strategy coverage would contaminate the data.

## 4. What we changed compared to upstream

Our code changes are marked `NLP RESEARCH EXTENSION`.

**Measurement**
- **Strategy logging** ([src/utils/strategy_logging.py](src/utils/strategy_logging.py), on by default through the launcher, `HONEYVAL_LOG_STRATEGY=1`). Attacker and defender are asked to write a 3–5 sentence `<STRATEGY>` before each action or response. It's taken from the first generation (never regenerated) and stripped before normal processing. Metadata records `strategy`, `strategy_valid`, `strategy_source` and `strategy_prompt_version` (currently `strategic-rationale-v3`). These are elicited self-reports, not hidden reasoning. Earlier pilots used other protocols; don't pool versions.
- **The attacker's history keeps its strategies** (v3). The attacker's own conversation history stores its full output, `<STRATEGY>` included, as upstream stores the raw output. Under v2 we stripped it, and DeepSeek stopped writing strategies after 3–5 steps (15% coverage in v2, against 99% for the defender). The defender's history still has strategies stripped. Its coverage was already 99%, and keeping them would grow every defender call.
- **Defender `raw_response`** is saved in `http-app-metadata.jsonl`.
- **Upstream prompts are unchanged.** The strategy instructions are inserted next to the ACTION/RESPONSE format examples; the `exploit`, `mislead` and other behavioural prompts in [src/benchmark_prompts.py](src/benchmark_prompts.py) are untouched.

**Models** ([src/utils/litellm_erb.py](src/utils/litellm_erb.py), [src/utils/constants.py](src/utils/constants.py))
- **NEAR AI routing.** Model IDs starting with `nearai/` go to NEAR AI's OpenAI-compatible endpoint with `NEARAI_API_KEY`. Two DeepSeek V4.1 Flash models are priced: `nearai/deepseek/deepseek-v4.1-flash` (standard) and `nearai/deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated` (refusals removed). Keep them in separate experiments. `reasoning_effort` has no effect on them.
- **GPT-6 / GPT-5.6.** Pricing added; `temperature` and `top_p` are not sent with reasoning effort, since these models reject them.
- **Direct OpenAI** calls work without Bifrost.

**Parsing** ([src/agents/simple_react_agent.py](src/agents/simple_react_agent.py))
- **Missing `</ACTION>` repair.** The abliterated DeepSeek often stops right after `</ACTION_BODY>`. Upstream counts that as `PARSING ERROR` (75% of steps in our first test). We add the missing tag in exactly that case only; repaired steps have `"action_close_repaired": true` in `agent-metadata.jsonl`, and `raw_response` keeps the original. Runs before commit `e334b7a` were parsed strictly. Report the repair rate per model.

**Robustness**
- Honeypot cleanup no longer crashes when a container failed to start, and task errors are logged with full tracebacks.
- The launcher builds the two Docker images (`fastapi-webapp-base`, `sandbox`) once before any worker starts, and refuses to run unless the sandbox firewall (`DOCKER-USER`) can be inspected. With `--honeypot_type rule-based` it also builds `baxbench-fastapi-webapp`.
- **BaxBench image fix:** that image is based on Debian bullseye, whose security updates moved to `archive.debian.org` after its end of life, so upstream's build fails with a 404 on `sqlite3`. The preflight adds one line pointing apt at the archive. The packages and the app code are unchanged.

**Tooling** (no effect on the experiments)
- `scripts/nlp/`: `setup.sh`, `experiment.sh`, `run_honeyval.sh` (loads keys, then runs `src/main.py`) and `preflight_images.py`.
- Analysis: `scripts/nlp/analysis_scripts/01_preproc.py` and [nlp_research_scripts/](nlp_research_scripts/README.md). `turftopic` was removed from `env.yaml` because it conflicts with `rich`; install analysis-only packages where you analyse, e.g. `python -m pip install sentence-transformers 'turftopic==0.28.0' 'rich==13.9.4'`.
- Human annotation: [annotation/potato/](annotation/potato/) (`python annotation/potato/prepare_dataset.py --help`).
- Tests: `tests/test_action_parsing.py`, `test_attacker_history.py`, `test_strategy_logging.py`, `test_experiment_launcher.py` and `test_preflight_images.py`.
