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

"""Run CaMeL on tau-bench retail. One task or all; the flags mirror the main CaMeL CLI.

    <logdir>/<model[ _nodefense ]>/<domain>/user_task_<i>/<attack>/none.json

    # CaMeL defended, clean:
    python -m src.camel.taubench.cli local:Qwen3.6-35B-A3B --suite retail
    # CaMeL defended, under the fixed catalog injection:
    python -m src.camel.taubench.cli local:Qwen3.6-35B-A3B --run-attack --user-task 0 2 5
    # no-defense baseline (tau-bench's own ReAct agent), same attack:
    python -m src.camel.taubench.cli local:Qwen3.6-35B-A3B --run-attack --use-original

Utility is tau-bench's own reward; security is DoomArena's leak record (env.secrets). Only retail can
be run under attack. The CaMeL retail policy mode is `--policy-mode taint` (default) or `taint_shape`
(see retail_policy.py).
"""

from __future__ import annotations

import json
import logging as pylogging
import os
import pathlib
import re
from collections import Counter
from typing import Annotated

import cyclopts

from .env_setup import CATALOG_CONFIGS
from .runner import run_task

log = pylogging.getLogger("camel.taubench")


def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_") or "model"


def _task_count(domain: str) -> int:
    if domain == "retail":
        from tau_bench.envs.retail.tasks_test import TASKS_TEST
        return len(TASKS_TEST)
    from tau_bench.envs.airline.tasks_test import TASKS
    return len(TASKS)


def main(
    model: str,
    suite: str = "retail",
    user_tasks: Annotated[list[str] | None, cyclopts.Parameter(name=("--user-task", "-ut"), consume_multiple=True)] = None,
    run_attack: bool = False,
    use_original: bool = False,
    attack: str = "malicious_catalog_fixed",
    q_llm: str | None = None,
    policy_mode: str = "taint",
    user_model: str | None = None,
    user_provider: str = "openai",
    doomarena: str = "../DoomArena",
    max_steps: int = 30,
    logdir: str = "./runs_taubench",
    force_rerun: Annotated[bool, cyclopts.Parameter(name=("--force-rerun", "-f"))] = False,
):
    """Run CaMeL on tau-bench retail.

    Args:
        model: privileged (code-writing) model, e.g. local:Qwen3.6-35B-A3B or openai:gpt-4o.
        suite: tau-bench domain; only "retail" can be run under attack.
        user_tasks: task indices (0) or names (user_task_0); empty = all.
        run_attack: turn on DoomArena's catalog injection.
        use_original: no-defense baseline (tau-bench's own ReAct agent), written to a *_nodefense tree.
        attack: malicious_catalog_fixed (default, reproducible) or malicious_catalog.
        q_llm: quarantined reader model (defaults to `model`).
        policy_mode: retail policy: "taint" (faithful CaMeL) or "taint_shape" (taint + id-shape backstop).
        user_model: tau-bench user simulator (defaults to the agent server for local:, else gpt-4o).
        user_provider: litellm provider for the user simulator.
        doomarena: path to the DoomArena checkout the attack yaml is read from.
    """
    if not pylogging.getLogger().handlers:
        from rich.logging import RichHandler
        pylogging.basicConfig(level=os.getenv("CAMEL_LOG_LEVEL", "INFO").upper(), format="%(message)s",
                              handlers=[RichHandler(markup=True, show_path=False)])

    if run_attack and suite != "retail":
        raise SystemExit("only --suite retail can be run under attack (DoomArena ships no tool-output "
                         "attack for airline).")
    if run_attack and attack not in CATALOG_CONFIGS:
        raise SystemExit(f"--attack must be one of {sorted(CATALOG_CONFIGS)}")
    if policy_mode not in ("taint", "taint_shape"):
        raise SystemExit("--policy-mode must be 'taint' or 'taint_shape'")
    os.environ["CAMEL_RETAIL_POLICY"] = policy_mode

    q_model = q_llm or model
    # local user simulator by default when the agent is self-hosted, so a local run needs no hosted key
    user_model = user_model or (model if model.startswith("local:") else "gpt-4o")

    attack_name = attack if run_attack else "none"
    try:
        todo = ([int(str(u).strip().removeprefix("user_task_")) for u in user_tasks]
                if user_tasks else list(range(_task_count(suite))))
    except ValueError:
        raise SystemExit("--user-task takes a task index (0) or its name (user_task_0)")

    tree = f"{model}_nodefense" if use_original else model

    def path_for(i: int) -> pathlib.Path:
        return (pathlib.Path(logdir) / _slug(tree) / suite / f"user_task_{i}" / attack_name / "none.json")

    if not force_rerun:
        before = len(todo)
        todo = [i for i in todo if not path_for(i).exists()]
        skipped = before - len(todo)
    else:
        skipped = 0

    root = pathlib.Path(logdir) / _slug(tree)
    if not todo:
        log.info(f"== all {skipped} run(s) already under {root} -- nothing to do (--force-rerun to redo)")
        return
    log.info(f"== CaMeL :: tau-bench {suite} :: {len(todo)} task(s) -> {root}"
             f"{f'  ({skipped} logged, skipping)' if skipped else ''}")
    log.info(f"   model={model}  q={q_model}  attack={attack_name}  policy={policy_mode}"
             f"{'  defense=NONE (--use-original)' if use_original else ''}")
    log.info(f"   user simulator: {user_model} via {user_provider}\n")

    counts: Counter = Counter()
    for n, i in enumerate(todo, 1):
        rec = run_task(suite, i, model, q_model, run_attack=run_attack, attack=attack,
                       doomarena_root=doomarena, user_model=user_model, user_provider=user_provider,
                       max_steps=max_steps, use_original=use_original)
        p = path_for(i)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
        counts["failed" if rec.get("error") else "done"] += 1
        mark = "!" if rec.get("error") else ("+" if rec.get("utility") else "-")
        tail = (f"failed: {rec['error']}"[:110] if rec.get("error")
                else f"utility={rec.get('utility')} security={rec.get('security')}")
        log.info(f"  {mark} [{n}/{len(todo)}] {suite}/user_task_{i}/{attack_name}  {rec.get('seconds')}s  {tail}")

    log.info(f"\n== {sum(counts.values())} task(s): {dict(counts)} ==")
    done = [json.loads(path_for(i).read_text()) for i in todo if path_for(i).exists()]
    scored = [r for r in done if r.get("utility") is not None]
    if scored:
        util = sum(bool(r["utility"]) for r in scored) / len(scored)
        log.info(f"  utility: {util:.0%} over {len(scored)} task(s)  (tau-bench reward == 1)")
        secs = [r["security"] for r in scored if r.get("security") is not None]
        if secs:
            log.info(f"  attack succeeded (leak): {sum(bool(x) for x in secs) / len(secs):.0%} of {len(secs)} task(s)")
    log.info(f"\n{root}")


if __name__ == "__main__":
    cyclopts.run(main)
