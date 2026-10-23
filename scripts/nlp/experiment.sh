#!/usr/bin/env bash
# NLP RESEARCH EXTENSION: guided/manual experiment launcher for Honeyval.
# Run from any directory: bash /path/to/honeyval/scripts/nlp/experiment.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Strategy capture is on for this NLP project, including manual CLI passthrough.
# Set HONEYVAL_LOG_STRATEGY=0 explicitly to disable it.
export HONEYVAL_LOG_STRATEGY="${HONEYVAL_LOG_STRATEGY:-1}"

ask() {
  # ask VARIABLE "Question" "default" (assigns to variable in caller)
  local reply=""
  read -r -p "$2 [$3]: " reply
  printf -v "$1" '%s' "${reply:-$3}"
}

check_isolation() {
  if ! sudo -n /sbin/iptables -S DOCKER-USER >/dev/null 2>&1; then
    echo "Cannot inspect DOCKER-USER firewall rules via sudo. Verify sandbox isolation first." >&2
    exit 1
  fi
}

run_command() {
  local -a cmd=("bash" "scripts/nlp/run_honeyval.sh" "$@")
  echo
  echo "Honeyval command:"
  printf ' %q' "${cmd[@]}"
  printf '\n'
  echo "NLP strategy logging: $HONEYVAL_LOG_STRATEGY"
  echo "API calls incur charges; cost limits are per individual trajectory, not total batch spending."

  # Test the launcher without starting containers or making API requests.
  if [[ "${HONEYVAL_DRY_RUN:-0}" == "1" ]]; then
    echo "DRY RUN: nothing started."
    return
  fi

  if [[ -t 0 ]]; then
    local confirm=""
    read -r -p "Start experiment? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || return 0
  fi

  check_isolation
  "${cmd[@]}"
}

summarize() {
  local experiment="$1"
  if [[ "${HONEYVAL_DRY_RUN:-0}" == "1" ]]; then return; fi
  echo
  echo "Task summaries:"
  grep -R 'Task finished. Number of errors:' "results/$experiment" --include='task.log' || true
  echo "JSONL counts:"
  if [[ -d "results/$experiment" ]]; then
    find "results/$experiment" -name '*.jsonl' -exec wc -l {} + || true
  fi
  echo "Sandbox firewall warnings:"
  grep -R 'iptables insert failed' "results/$experiment" --include='*.log' || true
}

MODE="${1:-}"
INTERACTIVE_MENU=0
if [[ -z "$MODE" ]]; then
  echo "Honeyval experiment"
  echo "1) Smoke test: 1 Login trajectory, 6 steps (original defaults)"
  echo "2) Pilot: 10 Login trajectories, 6 steps (original defaults)"
  echo "3) Manual setup: interactively configure models, apps, and settings"
  read -r -p "Choose [1/2/3]: " MODE
  INTERACTIVE_MENU=1
fi

case "$MODE" in
  3|manual)
    # Preserve the original direct-CLI mode for scripts and advanced users.
    if [[ "$INTERACTIVE_MENU" == 0 ]]; then shift; fi
    if [[ "$#" -gt 0 ]]; then
      run_command "$@"
      exit 0
    fi
    if [[ ! -t 0 ]]; then
      echo "Manual mode needs a terminal. Alternatively: experiment.sh manual --mode run ..." >&2
      exit 2
    fi

    STAMP="$(date +%Y%m%d-%H%M%S)"
    ask NAME "Experiment name" "nlp-astra-vs-luna-$STAMP"
    ask APPS_TEXT "Benchmark apps (space separated)" "Login Forum"
    ask ATTACKER "Attacker model" "openai/gpt-6-astra-python-curl"
    ask DEFENDER "Defender model" "openai/gpt-6-luna"
    ask PENTEST_PROMPT "Attacker prompt (exploit/exploit-detect/exploit-detect-hide)" "exploit"
    ask HONEYPOT_PROMPT "Defender instructions (mislead/none/convince/vulnerable/...)" "mislead"
    ask SAMPLES "Samples per app" "1"
    ask STEPS "Maximum attacker steps" "8"
    ask ATTACKER_EFFORT "Attacker reasoning effort" "medium"
    ask DEFENDER_EFFORT "Defender reasoning effort" "low"
    ask ATTACKER_LIMIT "Attacker cost limit in USD per trajectory" "5"
    ask DEFENDER_LIMIT "Defender cost limit in USD per trajectory" "2"

    [[ "$NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "Invalid experiment name" >&2; exit 2; }
    [[ "$SAMPLES" =~ ^[1-9][0-9]*$ && "$STEPS" =~ ^[1-9][0-9]*$ ]] || {
      echo "Samples and steps must be positive integers" >&2; exit 2;
    }
    [[ "$ATTACKER_LIMIT" =~ ^[0-9]+([.][0-9]+)?$ && "$DEFENDER_LIMIT" =~ ^[0-9]+([.][0-9]+)?$ ]] || {
      echo "Cost limits must be nonnegative numbers" >&2; exit 2;
    }
    case "$PENTEST_PROMPT" in exploit|exploit-detect|exploit-detect-hide) ;; *)
      echo "Invalid attacker prompt" >&2; exit 2 ;; esac
    case "$HONEYPOT_PROMPT" in none|mislead|convince|vulnerable|careful_pi|aggressive_pi) ;; *)
      echo "Invalid defender prompt" >&2; exit 2 ;; esac
    case "$ATTACKER_EFFORT" in low|medium|high|max) ;; *)
      echo "Invalid attacker reasoning effort" >&2; exit 2 ;; esac
    case "$DEFENDER_EFFORT" in low|medium|high|max) ;; *)
      echo "Invalid defender reasoning effort" >&2; exit 2 ;; esac

    read -r -a APPS <<< "$APPS_TEXT"
    (( ${#APPS[@]} > 0 )) || { echo "Specify at least one app" >&2; exit 2; }

    echo
    echo "Experiment: $NAME"
    echo "Attacker: $ATTACKER | Defender: $DEFENDER"
    echo "Apps: ${APPS[*]} | $SAMPLES samples/app | $STEPS max steps"
    echo "Prompts: $PENTEST_PROMPT / $HONEYPOT_PROMPT"
    run_command \
      --mode run \
      --meta_experiment_type "$NAME" \
      --benchmark_tasks agent-vs-http-app \
      --benchmark_apps "${APPS[@]}" \
      --pentest_model "$ATTACKER" \
      --honeypot_type llm \
      --honeypot_model "$DEFENDER" \
      --pentesting_prompt "$PENTEST_PROMPT" \
      --honeypot_additional_instructions "$HONEYPOT_PROMPT" \
      --n_samples "$SAMPLES" \
      --max_workers 1 \
      --pentest_max_steps "$STEPS" \
      --pentest_timeout 600 \
      --pentest_reasoning_effort "$ATTACKER_EFFORT" \
      --honeypot_reasoning_effort "$DEFENDER_EFFORT" \
      --pentest_cost_limit "$ATTACKER_LIMIT" \
      --honeypot_cost_limit "$DEFENDER_LIMIT"
    summarize "$NAME"
    exit 0
    ;;
  1|smoke)
    TYPE=smoke; SAMPLES=1; STEPS=6 ;;
  2|pilot)
    TYPE=pilot; SAMPLES=10; STEPS=6 ;;
  *)
    echo "Invalid choice" >&2; exit 2 ;;
esac

# Preserve the former smoke/pilot defaults for reproducibility.
if [[ "$INTERACTIVE_MENU" == 0 ]]; then shift; fi
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="nlp-${TYPE}-$STAMP"
if [[ -t 0 ]]; then
  ask NAME "Experiment name" "$NAME"
  ask SAMPLES "Samples" "$SAMPLES"
  ask STEPS "Maximum attacker steps" "$STEPS"
fi
[[ "$SAMPLES" =~ ^[1-9][0-9]*$ && "$STEPS" =~ ^[1-9][0-9]*$ ]] || {
  echo "Samples and steps must be positive integers" >&2; exit 2;
}
[[ "$NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "Invalid experiment name" >&2; exit 2; }
echo "Experiment: $NAME | samples=$SAMPLES | steps=$STEPS"
echo "Models: attacker GPT-5.4-mini, defender GPT-5.4-nano (original smoke/pilot defaults)"
run_command \
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
summarize "$NAME"
