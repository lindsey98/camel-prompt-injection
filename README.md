# `CaMeL`: [Defeating Prompt Injections by Design](https://arxiv.org/abs/2503.18813)

Edoardo Debenedetti<sup>1,3</sup>, Ilia Shumailov<sup>2</sup>, Tianqi Fan<sup>1</sup>, Jamie Hayes<sup>2</sup>, Nicholas Carlini<sup>2</sup>, Daniel Fabian<sup>1</sup>, Christoph Kern<sup>1</sup>, Chongyang Shi<sup>2</sup>, Florian Tramèr<sup>3</sup>

<sup>1</sup>Google, <sup>2</sup>Google DeepMind, and <sup>3</sup>ETH Zurich

> [!WARNING]
> This is a research artifact released to reproduce the results in our paper. The interpreter implementation likely contains bugs (e.g., it might throw uncaught exceptions and crash) and the implementation might not be fully secure.
>
> This is **not** a Google product, and we are not planning to provide support for and/or maintain this codebase.

## Pre-requisites

1. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Rename `.env.example` to `.env` and populate it with your API keys
   (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`).
3. Load the keys into your environment before running:
   ```bash
   set -a && source .env && set +a
   ```

The model is always passed as `provider:model_name`. The three best models by
no-attack CaMeL utility — used in the examples below — are:
`openai:o3-2025-04-16` (with `--reasoning-effort high`),
`openai:o4-mini-2025-04-16` (with `--reasoning-effort high`), 
`anthropic:claude-sonnet-4-5-20250929`, and 
`google:gemini-2.5-flash-lite`.

By default a run reports **utility** (no attack). Add `--run-attack` to also
report **security** under AgentDojo's `important_instructions` attack.

You can check the available models by running:
- For Gemini:
```bash
 python -c "import google.genai as genai; c = genai.Client(); [print(m.name) for m in c.models.list()]"
```
- For Claude:
```bash
python -c "import anthropic; c = anthropic.Anthropic(); print([m.id for m in c.models.list()])"
```

## Running modes

There are three ways to run, summarized here and detailed below:

| Mode | Flags | What it is |
| --- | --- | --- |
| **No CaMeL (baseline)** | `--use-original` | Native tool-calling API, no defense |
| **CaMeL, no policies** | *(none)* | CaMeL interpreter, security policies **off** |
| **CaMeL + policies** | two steps, see below | CaMeL interpreter with security policies enforced |

### 1. No CaMeL — native tool calling (`--use-original`)

No attack:
```bash
python main.py anthropic:claude-sonnet-4-5-20250929 --use-original
```

Under attack:
```bash
python main.py anthropic:claude-sonnet-4-5-20250929 --use-original --run-attack
```

### 2. CaMeL without security policies (single step)

Running CaMeL with **no extra flags** uses the CaMeL interpreter but does **not**
enforce any security policy (it uses a no-op policy engine internally). This is
the `+camel` configuration.

No attack:
```bash
python main.py anthropic:claude-sonnet-4-5-20250929 
```

Under attack:
```bash
python main.py anthropic:claude-sonnet-4-5-20250929 --run-attack
```

### 3. CaMeL with security policies (`+camel+secpol`) — two steps

> [!IMPORTANT]
> Security policies are **only** applied during *replay*. You must first do a
> normal CaMeL run (step 1) to generate the execution traces, then replay them
> with `--replay-with-policies` (step 2). The replay reuses the exact same
> generated code, so the policy is the only thing that changes — and it makes
> step 2 cheap, since it calls **no** LLM (the model outputs are read back from
> the saved trace).

No attack:
```bash
# Step 1 — generate the CaMeL traces (writes to ./logs/<model>+camel/...)
python main.py anthropic:claude-sonnet-4-5-20250929 

# Step 2 — replay the same code with security policies enforced
python main.py anthropic:claude-sonnet-4-5-20250929 --replay-with-policies
```

Under attack:
```bash
# Step 1 — generate the CaMeL traces (writes to ./logs/<model>+camel/...)
python main.py anthropic:claude-sonnet-4-5-20250929 --run-attack

# Step 2 — replay the same code with security policies enforced
python main.py anthropic:claude-sonnet-4-5-20250929 --run-attack --replay-with-policies
```

The model **must be identical** in both steps (the replay looks the trace up by
pipeline name). Do **not** pass `--q-llm` in step 1, or the trace path won't
match in step 2.

> [!NOTE]
> The trace path includes the attack name, so an attack run (step 1 with
> `--run-attack`) and a no-attack run are stored separately. Make sure step 1 and
> step 2 use the **same** `--run-attack` setting, or the replay won't find the
> matching traces.

## Common options

- `--run-attack` — also run the `important_instructions` attack and report
  security (omit it for utility-only / no-attack runs).
- `--reasoning-effort {low,medium,high}` — **only** affects OpenAI reasoning
  models (`o3`, `o4-mini`, `o1`, `codex`). Ignored by Gemini / Claude / GPT-4.1.
- `--thinking-budget-tokens N` — Anthropic thinking budget (e.g. `16000` for
  Claude Sonnet 4 with reasoning). This is separate from `--reasoning-effort`.
- `--suites workspace banking travel slack` — restrict to specific suites.
- `--user-tasks user_task_0 user_task_1` — restrict to specific user tasks.
- `--q-llm provider:model` — use a cheaper model as the quarantined LLM (only
  for single-step CaMeL runs, not for replay).
- `--eval-mode {normal,strict}` — dependency-propagation mode for policies
  (`strict` corresponds to `+camel+secpol+strict`).

Full list: `python main.py --help`.

### Examples

```bash
# Baseline (no CaMeL), with attack -> security numbers
python main.py anthropic:claude-sonnet-4-5-20250929 --use-original --run-attack

# OpenAI reasoning model with high reasoning effort, CaMeL + policies
python main.py openai:o3-2025-04-16 --reasoning-effort high
python main.py openai:o3-2025-04-16 --reasoning-effort high --replay-with-policies

# Claude Sonnet 4 with a 16k thinking budget, CaMeL + policies, workspace only
python main.py anthropic:claude-sonnet-4-5-20250929 --thinking-budget-tokens 16000 --suites workspace
python main.py anthropic:claude-sonnet-4-5-20250929 --thinking-budget-tokens 16000 --suites workspace --replay-with-policies
```

## Local / self-hosted models

You can run a local model (e.g. **Llama-3.3-70B**) as long as it is served behind
an **OpenAI-compatible HTTP endpoint** — both CaMeL LLMs (the privileged code
generator and the quarantined parser) talk to it over the OpenAI protocol.

1. Serve the model, for example with vLLM:
   ```bash
   vllm serve meta-llama/Llama-3.3-70B-Instruct \
     --served-model-name Llama-3.3-70B-Instruct \
     --enable-auto-tool-choice --tool-call-parser llama3_json
   ```
   (`--enable-auto-tool-choice` matters: the quarantined LLM relies on
   structured / tool-style output.)
2. Point CaMeL at the endpoint via environment variables:
   ```bash
   export LOCAL_BASE_URL=http://localhost:8000/v1
   export LOCAL_API_KEY=EMPTY   # whatever your server expects, if anything
   ```
3. Use the `local:` prefix with the **served model name**:
   ```bash
   # CaMeL without policies
   python main.py local:Llama-3.3-70B-Instruct

   # CaMeL + policies (two steps, as usual)
   python main.py local:Llama-3.3-70B-Instruct
   python main.py local:Llama-3.3-70B-Instruct --replay-with-policies

   # baseline (no CaMeL)
   python main.py local:Llama-3.3-70B-Instruct --use-original
   ```

Notes:
- The served model name must be registered in `_supported_model_names`
  (`src/camel/models.py`) so the attack/logging machinery can resolve it.
  `Llama-3.3-70B-Instruct` is already added; add other names there as needed.
- CaMeL leans heavily on the quarantined LLM producing **valid structured
  output** and the privileged LLM producing **valid Python**. Smaller/open models
  do this less reliably than frontier models, so expect more interpreter retries
  and `NotEnoughInformationError`s.
- To keep a strong privileged model but a cheap/local parser, pass
  `--q-llm local:Llama-3.3-70B-Instruct` (and remember to repeat it in step 2).
- **Native baseline (`--use-original`) + tool parsers:** some local tool-call
  parsers (e.g. vLLM's `llama3_json`) only allow one tool call per turn. CaMeL
  itself is unaffected (it generates Python, not tool calls), and for the native
  baseline the local client forces `parallel_tool_calls=False` automatically.
- **Context window:** the prompt (system prompt + tool schemas + accumulated tool
  outputs) must fit the model's context window. `workspace`/`travel` are the
  largest; `banking`/`slack` are much smaller. Serve with a large `--max-model-len`
  (Llama-3.3-70B supports up to 128k). If a prompt still overflows, that task is
  **skipped with a warning and scored as failed** rather than crashing the run, so
  the rest of the benchmark continues.

## FAQ

> How do I try a new/different model?

You can add it to the [`models.py`](src/camel/models.py) file, in the `_supported_model_names` variable. The keys are the model names with the given provider (check the provider's API) and the values is what the model says when asked "what model are you?". Keep in mind that OpenAI reasoning models are stored in the `_oai_thinking_models` variable instead.

