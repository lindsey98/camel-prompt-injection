#!/bin/bash
# Run the ASB Observation Prompt Injection (OPI) benchmark on a locally-served model.
#
# Usage:
#   bash scripts/run_opi.sh              # undefended baseline (expect ASR > 0)
#   bash scripts/run_opi.sh camel        # CaMeL defense
#
# Run from the asb/ directory. Requires a vLLM (or other OpenAI-compatible) endpoint; set
# LOCAL_BASE_URL / LOCAL_API_KEY if not the defaults (http://localhost:8000/v1, "EMPTY").
set -euo pipefail

DEFENSE="${1:-}"                                   # "" (baseline) or "camel"
MODEL="${MODEL:-Qwen3-30B-A3B-Instruct-2507}"      # must match the vLLM --served-model-name
ATTACK_TYPE="${ATTACK_TYPE:-context_ignoring}"
ATTACKER_TOOLS="${ATTACKER_TOOLS:-data/attack_tools_test.jsonl}"  # small slice for a smoke test
TASK_NUM="${TASK_NUM:-1}"

# Local vLLM is on localhost: never route it through an HTTP proxy.
export no_proxy="localhost,127.0.0.1,0.0.0.0${no_proxy:+,$no_proxy}"
export NO_PROXY="$no_proxy"

# ASB runs with cwd=asb (so aios/, pyopenagi/, camel_adapter/, data/ resolve). Also put the repo
# root on PYTHONPATH so the CaMeL kernel (src.camel) imports for the CaMeL defense.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$(pwd):${REPO_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

LABEL="${DEFENSE:-baseline}"
mkdir -p logs/observation_prompt_injection
RES="logs/observation_prompt_injection/${MODEL}_${ATTACK_TYPE}_${LABEL}.csv"

DEFENSE_ARG=()
[ -n "$DEFENSE" ] && DEFENSE_ARG=(--defense_type "$DEFENSE")

echo "Model=$MODEL  attack_type=$ATTACK_TYPE  defense=${LABEL}  attacker_tools=$ATTACKER_TOOLS"
python main_attacker.py \
  --llm_name "$MODEL" \
  --use_backend local \
  --observation_prompt_injection \
  --attack_type "$ATTACK_TYPE" \
  --attacker_tools_path "$ATTACKER_TOOLS" \
  --task_num "$TASK_NUM" \
  --database /nonexistent_no_memory_db \
  --res_file "$RES" \
  "${DEFENSE_ARG[@]}"
echo "Done. Results CSV: $RES"
