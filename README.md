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

### Optional: AgentDyn suites

To run the [AgentDyn](https://github.com/SaFo-Lab/AgentDyn) suites (`shopping`,
`github`, `dailylife`), install the AgentDyn fork of `agentdojo` **instead of**
the PyPI `agentdojo` pinned in `requirements.txt` (the fork keeps the same
package name and API, and also contains the original four suites):

```bash
pip uninstall -y agentdojo
git clone https://github.com/SaFo-Lab/AgentDyn.git
pip install -e ./AgentDyn
```

Then pass the new suites explicitly, e.g.:

```bash
python main.py MODEL --run-attack --suites shopping github dailylife
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

Add `--run-attack` to any mode to inject an attack and also report **security**;
otherwise only no-attack **utility** is reported. The attack defaults to AgentDojo's
`important_instructions`; pick another with `--attack NAME` (see
[Attacks](#attacks) below).

**CaMeL + policies** is two steps — policies are applied only on *replay*, which
reuses the saved traces (no LLM calls), so step 2 is cheap:

```bash
python main.py MODEL                          # step 1: generate traces
python main.py MODEL --replay-with-policies   # step 2: enforce policies
```

Use the **same** model, `--run-attack`, and `--attack` settings in both steps, and
do **not** pass `--q-llm` in step 1, or the replay won't find the traces (traces are
saved under a per-attack directory).

## Attacks

`--attack NAME` selects any attack registered in AgentDojo (e.g.
`important_instructions` (default), `ignore_previous`, `tool_knowledge`, `direct`,
`dos`). Also bundled is [**ChatInject**](https://github.com/hwanchang00/ChatInject),
which formats the injection as the target model's *own chat template* so the model
reads it as real conversation turns:

| `--attack` | Description |
| --- | --- |
| `chat_inject_qwen3` | Template-only (single fake system/user/assistant exchange), Qwen3 template |
| `chat_inject_glm` | Same, GLM-4.5 template |
| `chat_inject_qwen3_with_utility_system_multiturn_7` | Multi-turn benign dialogue then the goal, Qwen3 template |
| `chat_inject_qwen3_with_utility_authority_endorsement_system_multiturn_7` | Multi-turn with authority-endorsement persuasion, Qwen3 template |

(swap `qwen3`→`glm` for the GLM template of either multi-turn variant). Pick the
template that matches your `--model`; the wrong template silently no-ops.

```bash
python main.py local:Qwen3.6-35B-A3B --run-attack \
  --attack chat_inject_qwen3_with_utility_system_multiturn_7 --suites banking slack travel
```

The multi-turn variants load a **pre-generated per-goal dialogue** from
`src/camel/attacks/chatinject_data/`. The shipped data covers the banking / slack /
travel injection goals only; an uncovered goal (e.g. the AgentDyn suites) raises a
clear `ValueError`. The template-only variants work on every suite.

Also bundled are the **Cascade** ([arXiv:2510.05244](https://arxiv.org/abs/2510.05244),
Table 21) "Stage 2" second-order semantic-template attacks — deceptive wrappers that
drop instruction-like surface forms (several add a high-salience *decoy* to distract
format-driven defenses while the real payload rides along as trusted metadata):

| `--attack` | Strategy |
| --- | --- |
| `cascade_user_note` | Casual user-note framing (`Note from Emma Johnson: …`) |
| `cascade_task_queue` | Fake `=== Task Queue Status ===` operational formatting |
| `cascade_safe_tags` | Trusted-looking `<notapromptinjection>` wrapper (provenance cue) |
| `cascade_decoy_safe_tags` | High-salience `<promptinjection>` decoy + real payload in a safe wrapper |
| `cascade_skip_directive` | `<hidden_instruction>` + a "skip these tags" directive |
| `cascade_triple_layer` | decoy + `<notapromptinjection>` + `<hidden_instruction>` combined |
| `cascade_decoy_system_update` | decoy + urgent `<system_update verified="true">` wrapper |

These work on every suite. Templates are faithful reconstructions of Table 21's
descriptions (the paper does not publish verbatim strings).

## Common options

`--reasoning-effort {low,medium,high}` (OpenAI reasoning models only) ·
`--thinking-budget-tokens N` (Anthropic) ·
`--suites workspace banking travel slack` (plus `shopping github dailylife` with
[AgentDyn](#optional-agentdyn-suites) installed) · `--attack NAME` (see
[Attacks](#attacks)) · `--user-tasks user_task_0 ...` ·
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
