#!/usr/bin/env bash
# Run from any directory: bash /path/to/honeyval/scripts/nlp/experiment.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
MODE="${1:-}"
if [[ -z "$MODE" ]]; then
  echo "Honeyval experiment"
  echo "1) Smoke test: 1 Login trajectory, 6 steps"
  echo "2) Pilot: 10 Login trajectories, 6 steps"
  echo "3) Manual CLI: specify all Honeyval arguments"
  read -r -p "Choose [1/2/3]: " MODE
fi
case "$MODE" in
  1|smoke) TYPE=smoke; SAMPLES=1; STEPS=6 ;;
  2|pilot) TYPE=pilot; SAMPLES=10; STEPS=6 ;;
  3|manual)
    shift "$(( $# > 0 ? 1 : 0 ))"
    if [[ "$#" -eq 0 ]]; then
      echo "Manual usage: bash scripts/nlp/experiment.sh manual --mode run --meta_experiment_type my-run ..." >&2
      exit 2
    fi
    exec bash scripts/nlp/run_honeyval.sh "$@" ;;
  *) echo "Invalid choice" >&2; exit 2 ;;
esac
if [[ "$#" -gt 0 ]]; then shift; fi
# Extra CLI flags can override defaults, but avoid repeating a flag when possible.
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="nlp-${TYPE}-$STAMP"
if [[ -t 0 ]]; then
  read -r -p "Experiment name [$NAME]: " answer
  NAME="${answer:-$NAME}"
  read -r -p "Samples [$SAMPLES]: " answer
  SAMPLES="${answer:-$SAMPLES}"
  read -r -p "Maximum attacker steps [$STEPS]: " answer
  STEPS="${answer:-$STEPS}"
fi
[[ "$SAMPLES" =~ ^[1-9][0-9]*$ && "$STEPS" =~ ^[1-9][0-9]*$ ]] || { echo "Samples and steps must be positive integers" >&2; exit 2; }
echo "Experiment: $NAME | samples=$SAMPLES | steps=$STEPS"
echo "Models: attacker gpt-5.4-mini, defender gpt-5.4-nano"
echo "API calls are billable."
if [[ -t 0 ]]; then
  read -r -p "Start experiment? [y/N] " confirmed
  [[ "$confirmed" =~ ^[Yy]$ ]] || exit 0
fi
# Restrict manual execution until user has inspected the isolation logs/rules.
if ! sudo -n /sbin/iptables -S DOCKER-USER >/dev/null 2>&1; then
  echo "Cannot inspect DOCKER-USER rules via sudo. Verify sandbox isolation first." >&2
  exit 1
fi
bash scripts/nlp/run_honeyval.sh \
  --mode run \
  --meta_experiment_type "$NAME" \
  --benchmark_tasks agent-vs-http-app \
  --benchmark_apps Login \
  --pentest_model openai/gpt-5.4-mini-python-curl \
  --honeypot_type llm \
  --honeypot_model openai/gpt-5.4-nano \
  --pentesting_prompt exploit \
  --n_samples "$SAMPLES" \
  --max_workers 1 \
  --pentest_max_steps "$STEPS" \
  --pentest_timeout 300 \
  --pentest_reasoning_effort low \
  --honeypot_reasoning_effort low \
  --pentest_cost_limit 1 \
  --honeypot_cost_limit 1 \
  "$@"
echo
echo "Task summaries:"
grep -R 'Task finished. Number of errors:' "results/$NAME" --include='task.log' || true
echo "JSONL counts:"
find "results/$NAME" -name '*.jsonl' -exec wc -l {} + || true
echo "Sandbox firewall warnings:"
grep -R 'iptables insert failed' "results/$NAME" --include='*.log' || true
