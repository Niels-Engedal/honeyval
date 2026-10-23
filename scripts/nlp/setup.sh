#!/usr/bin/env bash
# Source this script so Conda activation and environment variables remain in
# the current terminal: source scripts/nlp/setup.sh
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Run this with: source scripts/nlp/setup.sh" >&2
  exit 1
fi

honeyval_setup() {
  local root project env_file conda_sh answer key
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || return 1
  project="$(dirname "$root")"
  env_file="${HONEYVAL_ENV_FILE:-$project/.secrets/honeyval.env}"
  conda_sh="/home/ucloud/miniconda3/etc/profile.d/conda.sh"

  [[ -f "$conda_sh" ]] || { echo "Miniconda not found at $conda_sh. Install it following the upstream README." >&2; return 1; }
  # shellcheck disable=SC1090
  source "$conda_sh" || return 1

  if ! conda env list | awk '$1 == "honeyval" {found=1} END {exit !found}'; then
    read -r -p "Create Conda environment 'honeyval' from env.yaml now? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || return 1
    (cd "$root" && conda env create -f env.yaml) || return 1
    conda activate honeyval || return 1
    (cd "$root" && python -m pip install 'litellm[proxy]' && python -m pip install -e .) || return 1
  else
    conda activate honeyval || return 1
  fi

  # Store credentials outside the Git checkout. Never print the key.
  if [[ ! -s "$env_file" ]]; then
    mkdir -p "$(dirname "$env_file")" || return 1
    chmod 700 "$(dirname "$env_file")" || return 1
    read -r -s -p "OpenAI API key (stored privately): " key
    echo
    [[ -n "$key" ]] || { echo "No key entered" >&2; return 1; }
    (umask 077; printf 'OPENAI_API_KEY=%q\n' "$key" > "$env_file") || return 1
    unset key
    chmod 600 "$env_file" || return 1
  fi
  if [[ -f "$env_file" ]] && [[ "$(stat -c %a "$env_file")" != "600" ]]; then
    chmod 600 "$env_file" || return 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$env_file" || { set +a; return 1; }
  set +a
  [[ -n "${OPENAI_API_KEY:-}" ]] || { echo "OPENAI_API_KEY missing in $env_file" >&2; return 1; }

  cd "$root" || return 1
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is not accessible in this terminal. Check the Docker service and group membership." >&2
    echo "If necessary run: newgrp docker   (then source this script again)." >&2
    return 1
  fi
  python - <<'PY'
import docker
client = docker.from_env()
assert client.ping(), "Docker ping failed"
client.close()
print("Python Docker connection: OK")
PY
  [[ $? -eq 0 ]] || return 1

  local leftovers
  leftovers="$(docker ps --format '{{.Names}}' | grep -E '^(agent-sandbox-|honeypot-Login-)' || true)"
  if [[ -n "$leftovers" ]]; then
    echo "Warning: existing Honeyval containers are running (possibly from interrupted experiments):"
    printf '%s\n' "$leftovers"
    echo "Do not delete them automatically if another experiment is running."
  fi

  echo "Ready: $(pwd)"
  echo "Conda: ${CONDA_DEFAULT_ENV:-unknown}; OpenAI API key: loaded (not displayed)"
  echo "Start a guided experiment: bash scripts/nlp/experiment.sh"
}

honeyval_setup
unset -f honeyval_setup
