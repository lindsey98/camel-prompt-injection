#!/bin/bash
# Clean (no-attack) run: measures the benign-task utility ceiling. Identical to run_opi.sh but with
# no OPI injection and no attacker tool (each task runs once). Traces land under
# logs/<model>_nodefense/<agent>/<user_task>/none/none.json  (or <model>+<defense> with a defense).
#
# Usage:
#   bash scripts/run_clean.sh          # no defense  -> utility ceiling
#   bash scripts/run_clean.sh camel    # CaMeL on benign tasks -> over-defense baseline
#
# All run_opi.sh knobs still apply as env vars, e.g.:
#   MODEL=Qwen3.6-35B-A3B TASK_NUM=6 MAX_WORKERS=16 bash scripts/run_clean.sh
exec env CLEAN=1 bash "$(dirname "$0")/run_opi.sh" "$@"
