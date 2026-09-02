#!/bin/bash
export NCCL_P2P_DISABLE=0
export NCCL_IB_DISABLE=1
export VLLM_USE_COMPILE=0
export OMP_NUM_THREADS=16
export NCCL_SOCKET_IFNAME=lo,eth0
export VLLM_NO_USAGE_STATS=1
export VLLM_ATTENTION_BACKEND=FLASH_ATTN
export no_proxy="localhost,127.0.0.1,0.0.0.0"

source activate vllm_env

CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 \
vllm serve /mnt/nvme0n1/ruofan/hf_hub/Llama-3.3-70B-Instruct \
  --dtype bfloat16 \
  --served-model-name Llama-3.3-70B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser llama3_json \
  --tensor-parallel-size 8 \
  --gpu-memory-utilization 0.92 \
  --max-num-seqs 16 \
  --max-num-batched-tokens 131072 \
  --max-model-len 131072 \
  --kv-cache-dtype fp8