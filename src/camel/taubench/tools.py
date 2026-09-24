# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Expose tau-bench's tools to CaMeL's interpreter.

Each tau-bench tool becomes an AgentDojo ``Function`` whose ``run`` calls ``tau_bench_env.step``.
The interpreter's ``AgentDojoFunction`` wrapper then tags the returned observation with the default
tool metadata -- ``sources.Tool(name, frozenset())`` (empty inner sources = **untrusted**), which is
exactly the taint the retail policy keys on. The DoomArena gateway (if present) wraps the same
``step``, so a poisoned ``get_product_details`` result arrives as an untrusted value like any other.

We do NOT expose a ``respond`` tool: talking to the user is the agent's job, done once per turn with
the code's printed output (see ``camel_agent``). Keeping ``respond`` out of the code avoids having to
interrupt interpretation mid-program.
"""

from __future__ import annotations

from typing import Any

import pydantic
from agentdojo import functions_runtime

# tau_bench is imported lazily inside the closure so this module imports without it installed
# (e.g. for a syntax check off the run host).

_JSON_TO_PY: dict[str, Any] = {
    "string": str, "integer": int, "number": float, "boolean": bool,
    "array": list, "object": dict,
}


def _normalize_schema(row: dict) -> tuple[str, str, dict]:
    """(name, description, json_schema) out of a tau-bench tool row (OpenAI function-calling shape)."""
    fn = row.get("function", row)
    return fn["name"], fn.get("description", ""), fn.get("parameters", {}) or {}


def _params_model(name: str, schema: dict) -> type[pydantic.BaseModel]:
    """A permissive pydantic model for a tool's arguments, built from its JSON Schema.

    Every field is Optional with default None so a call that omits an optional arg validates; unset
    Nones are filtered before reaching tau-bench (which does its own validation). Types map loosely;
    unknown types fall back to ``Any``.
    """
    props = (schema or {}).get("properties", {}) or {}
    fields: dict[str, tuple[Any, Any]] = {}
    for arg, spec in props.items():
        py = _JSON_TO_PY.get((spec or {}).get("type", "string"), Any)
        fields[arg] = (py | None, None)  # Optional, default None
    return pydantic.create_model(f"{name}_Args", **fields)  # type: ignore[call-overload]


class TauBenchState:
    """Mutable holder shared between the tool closures and the agent loop.

    tau-bench's ``env.step`` returns an ``EnvResponse(observation, reward, done, info)`` per call, but
    the interpreter only sees the observation a tool returns. The agent needs ``done`` / ``reward``
    too, so every tool call records its response here and the loop reads ``last`` afterwards.
    """

    def __init__(self, tb_env):
        self.env = tb_env
        self.last = None                 # the most recent EnvResponse
        self.tool_calls: list[dict] = []  # {name, kwargs, observation} per executed tool


def _make_run(state: TauBenchState, tool_name: str):
    def run(**kwargs):
        from tau_bench.types import Action

        clean = {k: v for k, v in kwargs.items() if v is not None}
        resp = state.env.step(Action(name=tool_name, kwargs=clean))
        state.last = resp
        obs = resp.observation if resp.observation is not None else ""
        state.tool_calls.append({"name": tool_name, "kwargs": clean, "observation": str(obs)})
        return str(obs)

    return run


def build_runtime(state: TauBenchState, tool_rows: list[dict]) -> functions_runtime.FunctionsRuntime:
    """A FunctionsRuntime holding every tau-bench tool, each bound to ``state.env.step``.

    The quarantined LLM (``query_ai_assistant``) is registered separately by the agent, the same way
    ``PrivilegedLLM.query`` does it.
    """
    runtime = functions_runtime.FunctionsRuntime([])
    for row in tool_rows:
        name, desc, schema = _normalize_schema(row)
        fn = functions_runtime.Function(
            name=name,
            description=(desc or name).split("\n")[0][:1000] or name,
            parameters=_params_model(name, schema),
            dependencies={},                       # no Depends: the closure holds the env
            run=_make_run(state, name),
            full_docstring=desc or name,
            return_type=str,
        )
        runtime.register_function(fn)
    return runtime
