"""Per-task token accounting for CaMeL, covering BOTH model roles, written into each record's JSON.

Why this exists: CaMeL's own `_report_qllm_token_usage` targets `agentdojo.logging.record_token_usage`,
which the installed AgentDojo does not provide (the call import-fails and is swallowed), and AgentDojo's
`OpenAILLM` does not report usage either -- so without this, every record is written with NO token count.

What it counts, comprehensively (like AgentPI):
  - the PRIVILEGED LLM (and the native `--use-original` baseline): AgentDojo's `OpenAILLM` uses the SYNC
    `openai` client, so we tally `response.usage` on `Completions.create`.
  - the QUARANTINED LLM (`query_ai_assistant`): it runs through pydantic-ai (an async client, so NOT the
    sync `Completions.create` above -- no double count); `quarantined_llm._report_qllm_token_usage` feeds
    its `run_result.usage()` here instead of the dead AgentDojo call.
Any other internal defense node that issues an `openai` chat completion is caught by the same sync patch.

Boundaries and output: AgentDojo's `TraceLogger` is entered once per task, so we reset at `__enter__` and
write the totals via `set_contextarg` at `__exit__` -- they land in the record JSON next to `duration`
(`prompt_tokens`, `completion_tokens`, `total_tokens`). Global counters -> runs must be sequential (which
the benchmark and the /metrics measurement already require); not thread-safe.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_prompt = 0
_completion = 0
_installed = False


def reset() -> None:
    global _prompt, _completion
    _prompt = 0
    _completion = 0


def add(prompt, completion) -> None:
    global _prompt, _completion
    try:
        _prompt += int(prompt or 0)
        _completion += int(completion or 0)
    except (TypeError, ValueError):
        pass


def totals() -> tuple[int, int]:
    return _prompt, _completion


def install() -> None:
    """Monkeypatch the sync openai client and AgentDojo's TraceLogger. Idempotent; call once before a run."""
    global _installed
    if _installed:
        return
    _installed = True

    # 1) Privileged LLM + native baseline + any sync-openai defense node.
    from openai.resources.chat import completions as _c

    _orig_create = _c.Completions.create

    def _create(self, *args, **kwargs):
        resp = _orig_create(self, *args, **kwargs)
        try:
            u = getattr(resp, "usage", None)
            if u is not None:
                add(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
        except Exception:  # noqa: BLE001 -- accounting must never break a generation
            pass
        return resp

    _c.Completions.create = _create

    # 2) Per-task boundary + write totals into the record (alongside `duration`).
    from agentdojo.logging import TraceLogger

    _orig_enter = TraceLogger.__enter__
    _orig_exit = TraceLogger.__exit__

    def _enter(self):
        reset()
        return _orig_enter(self)

    def _exit(self, exc_type, exc_value, traceback):
        p, c = totals()
        self.set_contextarg("prompt_tokens", p)
        self.set_contextarg("completion_tokens", c)
        self.set_contextarg("total_tokens", p + c)
        return _orig_exit(self, exc_type, exc_value, traceback)

    TraceLogger.__enter__ = _enter
    TraceLogger.__exit__ = _exit
    log.info("camel token_meter installed (P-LLM sync-openai + Q-LLM via _report_qllm_token_usage)")
