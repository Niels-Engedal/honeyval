
<div align="center">
    <h1><img height="150px" src="./assets/honeyval.png" alt="BaxBench"><br>Honeyval: A Comprehensive Evaluation Framework for LLM-powered Honeypots</h1>

  <a href="https://www.python.org/">
<img alt="Build" src="https://img.shields.io/badge/Python-3.12-1f425f.svg?color=blue">
  </a>
  <a href="https://opensource.org/licenses/MIT">
<img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg">
  </a>

</div>

## 👋 Overview

This is the source code for the Honeyval evaluation framework. The goal of the framework is to provide a systematic evaluation environment for LLM-powered HTTP honeypots. For more details, please read our [paper](https://arxiv.org/abs/2605.29963).

🌍 **Website & Leaderboard:** https://honeyval.xyz/

> This is not an officially supported Google product. This project is not
eligible for the [Google Open Source Software Vulnerability Rewards
Program](https://bughunters.google.com/open-source-security).


## NLP Masters / UCloud reproduction guide

For our fork's reproducible UCloud setup, private API-key handling, smoke test, 10-run pilot, and data logging, see **[README_NLP.md](README_NLP.md)**. This supplements the upstream instructions below and uses the same `src/main.py` CLI.

## Getting started

The project requires docker to be run. Please follow an installation guide fitting to your system [here](https://www.docker.com/get-started/).

The project uses miniconda for package management. Install it like this:

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
chmod +x Miniconda3-latest-Linux-x86_64.sh
bash ./Miniconda3-latest-Linux-x86_64.sh
```

Once installed, make sure that conda is initialized. Then, install the environment of this project:

```bash
conda env create -f env.yaml
conda activate honeyval
pip install litellm[proxy]
```

Then, a tiny little hack to use the `src` package:

```bash
# with the project environment activated
pip install -e .
```

Finally, to access the model APIs for running experiments, populate the following environment variables:

```bash
# we recommend using vertex for gemini models
export GOOGLE_CLOUD_PROJECT=""
export GOOGLE_APPLICATION_CREDENTIALS=""

# alternatively, you can use a gemini api key
export GEMINI_API_KEY=""

# other providers
export OPENAI_API_KEY=""
export TOGETHERAI_API_KEY=""
export ANTHROPIC_API_KEY=""
```

## Running experiments

`src/main.py` is the CLI entry point for running benchmarks and evaluating their
results. Run it from the repository root after activating the conda environment
and installing the package in editable mode.

```bash
python src/main.py \
  --mode run \
  --meta_experiment_type llm-honeypot-vs-agent \
  --pentest_model vertex_ai/gemini-3-flash-preview-python-curl \
  --honeypot_type llm \
  --honeypot_model vertex_ai/gemini-3-flash-preview \
  --benchmark_tasks agent-vs-http-app \
  --n_samples 5
```

Evaluate a completed run by reusing the same identifying options and changing
the mode:

```bash
python src/main.py \
  --mode evaluate \
  --meta_experiment_type llm-honeypot-vs-agent \
  --pentest_model vertex_ai/gemini-3-flash-preview-python-curl \
  --honeypot_type llm \
  --honeypot_model vertex_ai/gemini-3-flash-preview \
  --benchmark_tasks agent-vs-http-app \
  --n_samples 5 \
  --skip_incomplete
```

Useful options:

- `--mode`: `run`, `run-only-metrics`, or `evaluate`. This is required.
- `--meta_experiment_type`: names the experiment group under `results/`.
- `--benchmark_tasks`: one or more of `agent-vs-http-app`, `agent-vs-real`,
  `static-vs-http-app`, or `all`.
- `--benchmark_apps`: one or more benchmark app names, or `all`.
- `--pentest_model`: pentesting model. Suffix it with `-python-curl`,
  `-python`, `-gemini-cli`, `-codex`, or `-claude-code` to select that agent
  backend.
- `--honeypot_type`: `llm` or `rule-based`. For `llm`, also set
  `--honeypot_model`.
- `--pentesting_prompt`: `exploit`, `exploit-detect`, or `exploit-detect-hide`.
- `--honeypot_additional_instructions`: `none`, `careful_pi`,
  `aggressive_pi`, `mislead`, `convince`, or `vulnerable`.
- `--pi_judge` and `--refusal_judge`: `none`, `llm`, or `heuristic-llm`.
- `--n_samples`, `--max_workers`, `--starting_port`, and `--force` control
  sampling, parallelism, port allocation, and reruns.
- `--pentest_timeout`, `--pentest_max_steps`, cost limits, rate limits,
  temperatures, and reasoning efforts tune agent and honeypot execution.
- `--ci_target`, `--target_password`, and `--attacker_domain` configure the
  callback checks used by relevant benchmark apps.

Runs are written to
`results/<meta_experiment_type>/<pentest>-<prompt>-<honeypot>-<instructions>/`.
The scripts in `scripts/experiments_paper/` contain the exact configurations
used for the paper experiments. 

## Reproducing the paper

To reproduce the results of the paper, run the scripts in `scripts/experiments_paper`. Before running, we recommend building all docker images by running `python scripts/build_all_dockerimages.py`.

## Evaluating your own honeypot

To add your own honeypot to the evaluation, please implement the abstract interface `src/http_apps/base_http_app.py` in `src`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

This repository uses pre-commit hooks. The project conda environment installs
the `pre-commit` package; if you are not using that environment, install it
with `pip install pre-commit`. Then install the hooks:

```bash
pre-commit install
```

## How to cite

If you use Honeyval in your work, please cite our paper:

```bibtex
@misc{vero2026honeyvalcomprehensiveevaluationframework,
      title={Honeyval: A Comprehensive Evaluation Framework for LLM-powered HTTP Honeypots}, 
      author={Mark Vero and Fabian Kaczmarczyck and Ivan Petrov and Ilia Shumailov and Jamie Hayes and Niels Heinen and Tianqi Fan and Luca Invernizzi and Martin Vechev},
      year={2026},
      eprint={2605.29963},
      archivePrefix={arXiv},
      primaryClass={cs.CR},
      url={https://arxiv.org/abs/2605.29963}, 
}
```

## License
See `LICENSE.md`
