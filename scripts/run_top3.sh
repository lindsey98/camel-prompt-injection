#!/usr/bin/env bash
# Run the top-3 CaMeL models (by no-attack utility) through the +camel+secpol
# pipeline: utility (no attack) and security (important_instructions attack).
#
# Each configuration is two steps:
#   step 1: generate CaMeL traces
#   step 2: replay the same traces with security policies enforced
#
# Usage:
#   set -a && source .env && set +a
#   ./scripts/run_top3.sh
#
# Optional env override:
#   SUITES="--suites workspace" ./scripts/run_top3.sh
set -euo pipefail

SUITES="${SUITES:-}"   # e.g. "--suites workspace banking"

# model id + per-model flags (top 3 by CaMeL utility)
MODELS=(
  "openai:o3-2025-04-16|--reasoning-effort high"
  "openai:o4-mini-2025-04-16|--reasoning-effort high"
  "anthropic:claude-sonnet-4-20250514|"
)

run_two_step() {
  local model="$1"; local flags="$2"; local extra="$3"; local label="$4"
  echo "=================================================================="
  echo ">>> ${label}: ${model} ${flags} ${extra}"
  echo "=================================================================="
  # shellcheck disable=SC2086
  python main.py "$model" $flags $extra $SUITES
  # shellcheck disable=SC2086
  python main.py "$model" $flags $extra $SUITES --replay-with-policies
}

for entry in "${MODELS[@]}"; do
  model="${entry%%|*}"
  flags="${entry#*|}"
  # utility (no attack)
  run_two_step "$model" "$flags" "" "utility (no attack)"
  # security (with the important_instructions attack)
  run_two_step "$model" "$flags" "--run-attack" "security (important_instructions)"
done

echo "All runs complete."
