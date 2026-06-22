# `CaMeL`: [Defeating Prompt Injections by Design](https://arxiv.org/abs/2503.18813)

Edoardo Debenedetti<sup>1,3</sup>, Ilia Shumailov<sup>2</sup>, Tianqi Fan<sup>1</sup>, Jamie Hayes<sup>2</sup>, Nicholas Carlini<sup>2</sup>, Daniel Fabian<sup>1</sup>, Christoph Kern<sup>1</sup>, Chongyang Shi<sup>2</sup>, Florian Tramèr<sup>3</sup>

<sup>1</sup>Google, <sup>2</sup>Google DeepMind, and <sup>3</sup>ETH Zurich

> [!WARNING]
> Research artifact to reproduce the paper's results. The interpreter may contain bugs (it can throw and crash) and may not be fully secure. This is **not** a Google product and is not maintained.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY
set -a && source .env && set +a
```

Models are passed as `provider:model_name`, e.g. `openai:o3-2025-04-16`,
`anthropic:claude-sonnet-4-5-20250929`, `google:gemini-2.5-pro-preview-06-05`, or
`local:<name>` (see [Local models](#local--self-hosted-models)).

## Running

| Mode | Command |
| --- | --- |
| **No CaMeL** (baseline) | `python main.py MODEL --use-original` |
| **CaMeL**, no policies | `python main.py MODEL` |
| **CaMeL + policies** | two steps (below) |

Add `--run-attack` to any mode to inject AgentDojo's `important_instructions`
attack and also report **security**; otherwise only no-attack **utility** is reported.

**CaMeL + policies** is two steps — policies are applied only on *replay*, which
reuses the saved traces (no LLM calls), so step 2 is cheap:

```bash
python main.py MODEL                          # step 1: generate traces
python main.py MODEL --replay-with-policies   # step 2: enforce policies
```

Use the **same** model and `--run-attack` setting in both steps, and do **not**
pass `--q-llm` in step 1, or the replay won't find the traces.

## Common options

`--reasoning-effort {low,medium,high}` (OpenAI reasoning models only) ·
`--thinking-budget-tokens N` (Anthropic) ·
`--suites workspace banking travel slack` · `--user-tasks user_task_0 ...` ·
`--q-llm provider:model` (cheaper quarantined LLM; single-step only) ·
`--eval-mode {normal,strict}` · `--force-rerun`.
Full list: `python main.py --help`.

## Local / self-hosted models

Serve the model behind an OpenAI-compatible endpoint (vLLM / Ollama / TGI) and use
the `local:` prefix:

```bash
vllm serve meta-llama/Llama-3.3-70B-Instruct --served-model-name Llama-3.3-70B-Instruct \
  --enable-auto-tool-choice --tool-call-parser llama3_json --max-model-len 131072
export LOCAL_BASE_URL=http://localhost:8000/v1 LOCAL_API_KEY=EMPTY
python main.py local:Llama-3.3-70B-Instruct   # add --use-original / --replay-with-policies as needed
```

Notes:
- Register new served names in `_supported_model_names` (`src/camel/models.py`).
- Serve a large `--max-model-len` (workspace/travel prompts are big); over-long
  prompts are skipped (scored as failed) rather than crashing the run.
- Open models retry more (weaker structured output / Python). `CAMEL_DEBUG_QLLM=1`
  prints the quarantined-LLM input/output for debugging.

## FAQ

**Add a model:** add it to `_supported_model_names` in [`models.py`](src/camel/models.py)
(OpenAI reasoning models go in `_oai_thinking_models`).
