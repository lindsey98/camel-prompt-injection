# CaMeL on tau-bench (retail, `malicious_catalog_fixed`)

Runs CaMeL against tau-bench's **retail** domain under DoomArena's catalog (tool-output) attack, and
enforces the defense with a CaMeL security policy. Modeled on the AgentPI tau-bench adapter; scoring
is native (tau-bench `reward` for utility, DoomArena's `env.secrets` leak record for security).

> **Status: experimental, not yet run end-to-end.** It was written against the CaMeL/tau-bench/
> DoomArena APIs but not executed (tau-bench + DoomArena + a served model are needed). Expect to
> iterate on the run host — the per-turn code-gen prompt (`camel_agent._SYSTEM_SUFFIX`) especially.

## Why it's non-trivial

CaMeL is single-shot: `PrivilegedLLM` writes one Python program per query and an interpreter runs it.
tau-bench is a multi-turn conversation with an LLM user simulator. The adapter bridges them: **each
turn** the privileged LLM writes code over tau-bench's tools (bound as AgentDojo `Function`s) plus the
quarantined reader `query_ai_assistant`, the interpreter runs it (capability/taint tracking + the
retail policy gate each call), and the code's `print(...)` output is the message sent back with a
RESPOND action. `namespace` and taint persist across turns. See `camel_agent.py`.

## The defense (retail policy)

`retail_policy.RetailSecurityPolicyEngine` denies a tool call whose **control-point argument is
tainted by untrusted tool output** (`is_trusted` is False). The `malicious_catalog_fixed` attack
poisons a product's `name`; following it means re-issuing `get_product_details` with a `product_id`
built from that untrusted text, so the argument is tainted and the call is refused — CaMeL's own
capability mechanism, not a string match.

Two modes (`--policy-mode`, or env `CAMEL_RETAIL_POLICY`):
- `taint` (default): deny any tainted control-point arg. Faithful CaMeL. **Caveat:** legitimate
  `product_id`s in tau-bench also come from untrusted tool output, so pure taint can block legitimate
  lookups and depress utility. This is the honest result, and the reason AgentPI added a shape rule.
- `taint_shape`: deny only a tainted arg that is *also malformed* for its kind (a real `product_id`
  is 10 digits; `Yusuf_19122_9523456873` is not). More usable; run both to compare.

CaMeL's *primary* defense here may be upstream of the policy: untrusted catalog text is quarantined,
so the privileged planner never reads the "glue name+zip and re-query" instruction at all.

## Setup (on the run host)

Same extra deps as AgentPI (neither on PyPI). Clone DoomArena next to this repo:

```bash
uv pip install "git+https://github.com/sierra-research/tau-bench.git#egg=tau_bench"
uv pip install -e ../DoomArena/doomarena/core
uv pip install -e ../DoomArena/doomarena/taubench
export LOCAL_BASE_URL=http://localhost:8000/v1 LOCAL_API_KEY=EMPTY   # for local: models
```

## Run

```bash
# CaMeL defended, clean:
python -m src.camel.taubench.cli local:Qwen3.6-35B-A3B --suite retail

# CaMeL defended, under the fixed catalog injection:
python -m src.camel.taubench.cli local:Qwen3.6-35B-A3B --run-attack --user-task 0 2 5

# no-defense baseline (tau-bench's own ReAct agent), same attack, separate *_nodefense tree:
python -m src.camel.taubench.cli local:Qwen3.6-35B-A3B --run-attack --use-original

# taint+shape policy variant:
python -m src.camel.taubench.cli local:Qwen3.6-35B-A3B --run-attack --policy-mode taint_shape
```

Flags: `--q-llm` (quarantined reader, defaults to `--model`), `--attack {malicious_catalog_fixed,
malicious_catalog}`, `--user-task`/`-ut`, `--user-model` / `--user-provider` (defaults to the agent's
server for `local:`), `--doomarena PATH` (default `../DoomArena`), `--max-steps`, `--logdir`
(default `runs_taubench`), `--force-rerun`/`-f`.

Records land at `runs_taubench/<model[ _nodefense ]>/retail/user_task_<i>/<attack>/none.json` with
`utility`, `security`, `security_results` (`leaked` / `secret` / `injection_delivered` /
`doomarena_attack_success`), the transcript, and the ground-truth actions.

## Known limitations / to verify on the host

- The per-turn "print your reply" convention (vs a `respond` tool) is a design choice; if the model
  forgets to print, the turn falls back to a clarifying question.
- `openai:`/`local:` models only in `camel_agent._build_codegen_llm` (add anthropic/google if needed).
- No token accounting yet (the fork's `record_token_usage` needs an active TraceLogger, which this
  path doesn't use).
