"""Render an AgentDojo TraceLogger record (the dict saved as `<injection|none>.json`) into a
self-contained, human-readable HTML companion saved right next to it -- `none.json` -> `none.html`,
`injection_task_1.json` -> `injection_task_1.html`, same folder, same basename.

It renders the plain agentdojo trace that CaMeL runs write via `agentdojo.logging.TraceLogger`
(`{logdir}/{pipeline}/{suite}/{user_task}/{attack}/{injection|none}.json`, a ChatML `messages` list).

It renders only FACTS in the record -- the messages, tool calls, results, and the scores. It never
invents the "why did this pass/fail" commentary of the hand-made case figures; that is a human's.

`enable_trace_html()` monkeypatches `TraceLogger.save` so every trace the benchmark writes also gets
its HTML. It is idempotent and only takes effect when called (wired to the `--html` CLI flag).
"""

from __future__ import annotations

import json
import warnings
from html import escape
from pathlib import Path

_CSS = """
:root { --sys:#64748b; --usr:#2563eb; --ast:#16a34a; --tool:#d97706; }
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:"Helvetica Neue", Arial, sans-serif; background:#fff; display:flex; justify-content:center; padding:24px; }
.figure { width:940px; }
.title { font-size:15px; font-weight:700; color:#111; margin-bottom:4px; }
.title span { font-weight:400; color:#666; font-size:13px; }
.subnote { font-size:11.5px; color:#94a3b8; margin-bottom:12px; }
.msg { border:1.5px solid; border-radius:8px; padding:10px 14px; margin-bottom:10px; font-size:12.5px; line-height:1.45; color:#1f2937; position:relative; }
.role { display:inline-block; font-size:10.5px; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; color:#fff; border-radius:4px; padding:2px 8px; margin-bottom:6px; }
.sys { border-color:var(--sys); background:#f8fafc; } .sys .role { background:var(--sys); }
.usr { border-color:var(--usr); background:#eff6ff; } .usr .role { background:var(--usr); }
.ast { border-color:var(--ast); background:#f0fdf4; } .ast .role { background:var(--ast); }
.tool { border-color:var(--tool); background:#fffbeb; margin-left:32px; } .tool .role { background:var(--tool); }
.text { white-space:pre-wrap; }
code, .mono { font-family:"SF Mono", Menlo, Consolas, monospace; font-size:11.5px; }
.code { background:#ecfdf5; border:1px solid #86efac; border-radius:6px; padding:6px 10px; margin-top:6px; display:block; white-space:pre-wrap; overflow-x:auto; color:#14532d; }
.call { background:#dcfce7; border:1px solid #86efac; border-radius:6px; padding:6px 10px; margin-top:6px; display:block; white-space:pre-wrap; }
.result { background:#fef3c7; border:1px solid #fcd34d; border-radius:6px; padding:6px 10px; margin-top:4px; display:block; white-space:pre-wrap; overflow-x:auto; max-height:320px; overflow-y:auto; }
.result.err { background:#fee2e2; border-color:#fca5a5; color:#7f1d1d; }
.hl { background:#fde68a; font-weight:700; }
.badge { display:inline-block; font-size:10px; font-weight:700; letter-spacing:.05em; text-transform:uppercase; color:#fff; border-radius:4px; padding:1px 7px; margin-left:4px; }
.ok { background:#16a34a; } .bad { background:#b91c1c; }
.stop-badge { position:absolute; top:10px; right:12px; background:#334155; color:#fff; font-size:10.5px; font-weight:700; border-radius:4px; padding:2px 8px; letter-spacing:0.06em; }
.errline { font-size:11.5px; color:#7f1d1d; margin-top:8px; border-top:1px dashed #fca5a5; padding-top:8px; }
"""


def _text(content) -> str:
    """Flatten agentdojo message content (str, or a list of {type,content|text} blocks) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(str(b.get("content", b.get("text", ""))))
            else:
                parts.append(str(b))
        return "".join(parts)
    return str(content)


def _fmt_call(tc: dict) -> str:
    """`func(a=1, b="x")` from a tool_call dict {function, args}."""
    fn = tc.get("function", "?")
    args = tc.get("args") or {}
    if isinstance(args, dict):
        inner = ", ".join(f"{k}={v!r}" for k, v in args.items())
    else:
        inner = repr(args)
    return f"{fn}({inner})"


def _highlight(escaped_text: str, injections) -> str:
    """Wrap any injected string (already-escaped) found in the (already-escaped) text with .hl."""
    if not injections:
        return escaped_text
    values = injections.values() if isinstance(injections, dict) else injections
    for v in values:
        v = str(v).strip()
        if len(v) < 4:
            continue
        needle = escape(v)
        if needle in escaped_text:
            escaped_text = escaped_text.replace(needle, f'<span class="hl">{needle}</span>')
    return escaped_text


def _tick(v) -> str:
    return "✓" if v else "✗"


def render_trace_html(rec: dict) -> str:
    """Render one agentdojo trace record dict into a standalone HTML page (a string)."""
    suite = rec.get("suite_name", "?")
    utask = rec.get("user_task_id", "?")
    itask = rec.get("injection_task_id")
    attack = rec.get("attack_type") or "none"
    pipeline = rec.get("pipeline_name", "?")
    injections = rec.get("injections") or {}
    messages = rec.get("messages") or []
    utility = rec.get("utility")
    security = rec.get("security")
    duration = rec.get("duration")
    err = rec.get("error")

    n_calls = sum(len(m.get("tool_calls") or []) for m in messages if m.get("role") == "assistant")
    has_system = any(m.get("role") == "system" for m in messages)

    scen = f"user_task: {utask}"
    if itask:
        scen += f" · injection: {itask}"
    # agentdojo's `security` field flips meaning by run type: for an attack run True means the injection
    # SUCCEEDED (unsafe); for a clean run True is agentdojo's trivial "no attack -> secure". So safety is
    # "no real attack succeeded" -- which shows the clean run as security ✓, matching the case figures.
    attack_is_real = attack not in (None, "", "none")
    attack_succeeded = bool(attack_is_real and security)
    util_badge = f'<span class="badge {"ok" if utility else "bad"}">utility {_tick(utility)}</span>'
    sec_badge = "" if security is None else \
        f'<span class="badge {"bad" if attack_succeeded else "ok"}">security {_tick(not attack_succeeded)}</span>'

    subnote_bits = []
    subnote_bits.append("system message present" if has_system else "no system message")
    subnote_bits.append(f"{n_calls} tool call{'s' if n_calls != 1 else ''}")
    if isinstance(duration, (int, float)):
        subnote_bits.append(f"{duration:.2f} s")

    cards: list[str] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            body = escape(_text(m.get("content")))
            cards.append(f'<div class="msg sys"><span class="role">System</span><div class="text">{body}</div></div>')
        elif role == "user":
            body = escape(_text(m.get("content")))
            cards.append(f'<div class="msg usr"><span class="role">User</span><div class="text">{body}</div></div>')
        elif role == "assistant":
            inner = ['<span class="role">Assistant</span>']
            txt = _text(m.get("content")).strip()
            if txt:
                if "\n" in txt:
                    inner.append(f'<code class="code">{escape(txt)}</code>')
                else:
                    inner.append(f'<div class="text">{escape(txt)}</div>')
            for tc in (m.get("tool_calls") or []):
                inner.append(f'<code class="call">→ {escape(_fmt_call(tc))}</code>')
            cards.append(f'<div class="msg ast">{"".join(inner)}</div>')
        elif role == "tool":
            is_err = bool(m.get("error"))
            body = _highlight(escape(_text(m.get("content"))), injections)
            if is_err:
                body = escape(str(m.get("error"))) + ("\n" + body if body else "")
            cls = "result err" if is_err else "result"
            cards.append(f'<div class="msg tool"><span class="role">Tool</span>'
                         f'<code class="{cls}">{body}</code></div>')

    # a small end-of-trace marker on the last assistant card is nice, but keeping it simple: a footer badge
    err_html = f'<div class="errline"><b>error:</b> {escape(str(err))}</div>' if err else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Trace — {escape(suite)} / {escape(utask)} ({escape(attack)})</title>
<style>{_CSS}</style>
</head>
<body>
<div class="figure">
  <div class="title">Execution Trace <span>— AgentDojo · suite: {escape(suite)} · {escape(scen)} · attack: {escape(attack)} · {escape(pipeline)}</span> {util_badge}{sec_badge}</div>
  <div class="subnote">{escape(' · '.join(subnote_bits))}</div>
  {''.join(cards)}
  {err_html}
</div>
</body>
</html>
"""


def write_trace_html(json_path: str | Path) -> Path | None:
    """Render the trace JSON at `json_path` to a sibling `.html`. Returns the html path (or None on error)."""
    json_path = Path(json_path)
    try:
        rec = json.loads(json_path.read_text())
        html_path = json_path.with_suffix(".html")
        html_path.write_text(render_trace_html(rec))
        return html_path
    except Exception as e:  # a broken render must never break the benchmark run
        warnings.warn(f"trace_html: could not render {json_path}: {e}")
        return None


_PATCHED = False


def enable_trace_html() -> None:
    """Monkeypatch agentdojo's TraceLogger.save so every trace it writes also gets an .html companion.

    Idempotent. Call once (wired to --html) before running the benchmark.
    """
    global _PATCHED
    if _PATCHED:
        return
    from agentdojo import logging as ad_logging

    _orig_save = ad_logging.TraceLogger.save

    def _save_with_html(self):
        _orig_save(self)
        try:
            pipeline_name = self.context.get("pipeline_name")
            attack_type = self.context.get("attack_type")
            if pipeline_name is None or attack_type is None:
                return  # save() itself skipped it (warned already)
            suite_name = self.context.get("suite_name", "unknown_suite_name")
            user_task_id = self.context.get("user_task_id", "unknown_user_task_id")
            injection_task_id = self.context.get("injection_task_id")
            directory = (Path(self.dirpath) / pipeline_name.replace("/", "_")
                         / suite_name / user_task_id / attack_type)
            write_trace_html(directory / f"{injection_task_id or 'none'}.json")
        except Exception as e:
            warnings.warn(f"trace_html: post-save render failed: {e}")

    ad_logging.TraceLogger.save = _save_with_html
    _PATCHED = True
