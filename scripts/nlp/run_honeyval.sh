#!/usr/bin/env bash
# Minimal wrapper: load private credentials, then run the upstream Honeyval CLI.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${HONEYVAL_ENV_FILE:-/work/honeyval_project/.secrets/honeyval.env}"
if [[ ! -r "$ENV_FILE" ]]; then
  echo "Missing private credential file: $ENV_FILE" >&2
  exit 1
fi
set -a
# Only source credential files you personally created/trust.
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is unset or empty in credential file" >&2
  exit 1
fi
cd "$ROOT"
if [[ -x /home/ucloud/miniconda3/envs/honeyval/bin/python ]]; then
  exec /home/ucloud/miniconda3/envs/honeyval/bin/python src/main.py "$@"
fi
exec python src/main.py "$@"
