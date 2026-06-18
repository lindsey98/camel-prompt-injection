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
`google:gemini-flash-latest`.

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

```bash
python main.py anthropic:claude-sonnet-4-5-20250929 
```

Add ``--run-attack`` if you want to run under attack.

### 3. CaMeL with security policies (`+camel+secpol`) — two steps

> [!IMPORTANT]
> Security policies are **only** applied during *replay*. You must first do a
> normal CaMeL run (step 1) to generate the execution traces, then replay them
> with `--replay-with-policies` (step 2). The replay reuses the exact same
> generated code, so the policy is the only thing that changes — and it makes
> step 2 cheap, since it calls **no** LLM (the model outputs are read back from
> the saved trace).

```bash
# Step 1 — generate the CaMeL traces (writes to ./logs/<model>+camel/...)
python main.py anthropic:claude-sonnet-4-5-20250929 

# Step 2 — replay the same code with security policies enforced
python main.py anthropic:claude-sonnet-4-5-20250929 --replay-with-policies
```
Add ``--run-attack`` if you want to run under attack.

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

## FAQ

> How do I try a new/different model?

You can add it to the [`models.py`](src/camel/models.py) file, in the `_supported_model_names` variable. The keys are the model names with the given provider (check the provider's API) and the values is what the model says when asked "what model are you?". Keep in mind that OpenAI reasoning models are stored in the `_oai_thinking_models` variable instead.

