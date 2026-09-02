#!/bin/bash
export NCCL_P2P_DISABLE=0
export NCCL_IB_DISABLE=1
export VLLM_USE_COMPILE=0
export OMP_NUM_THREADS=16
export NCCL_SOCKET_IFNAME=lo,eth0
export VLLM_NO_USAGE_STATS=1
export VLLM_ATTENTION_BACKEND=FLASH_ATTN
export no_proxy="localhost,127.0.0.1,0.0.0.0"


CUDA_VISIBLE_DEVICES=4,5,6,7 \
vllm serve /mnt/nvme0n1/ruofan/hf_hub/Qwen3-30B-A3B-Instruct-2507 \
  --dtype bfloat16 \
  --served-model-name Qwen3-30B-A3B-Instruct-2507 \
  --host 0.0.0.0 \
  --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --tensor-parallel-size 4 \
  --gpu-memory-utilization 0.92 \
  --max-num-seqs 32 \
  --max-num-batched-tokens 262144 \
  --max-model-len 131072 \
  --kv-cache-dtype auto \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --scheduling-policy priority