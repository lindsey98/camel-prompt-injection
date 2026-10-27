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

"""tau-bench + DoomArena wiring (framework glue only -- no CaMeL logic here).

Adapted from AgentPI's tau-bench adapter. Scope is deliberately narrow: retail domain, the
``malicious_catalog_*`` catalog (tool-output) attacks only. The user-channel attacks DoomArena also
ships are out of scope (an attacker who *is* the user is a different threat model), so only
``type: database`` components of the attack yaml are used.
"""

from __future__ import annotations

import logging
import os
import pathlib

import yaml
from litellm import completion
from doomarena.taubench.attack_gateway import TauBenchAttackGateway
from doomarena.taubench.scripts.attack_script import fetch_attack_configs
from tau_bench.envs import get_env
from tau_bench.envs.user import LLMUserSimulationEnv

log = logging.getLogger(__name__)

#: DoomArena ships its attack definitions as yaml; we load THEIRS rather than re-encode them.
#: `malicious_catalog_fixed` (the default) writes a constant injection string into a product's `name`
#: -- no attacker model, reproducible. `malicious_catalog` regenerates it each call via openrouter.
_CONFIG_DIR = "doomarena/taubench/src/doomarena/taubench/scripts"
CATALOG_CONFIGS = {
    "malicious_catalog": "malicious_catalog_retail_attack.yaml",
    "malicious_catalog_fixed": "malicious_catalog_fixed_injection_retail_attack.yaml",
}


class DeterministicUser(LLMUserSimulationEnv):
    """tau-bench's user simulator, decoded greedily.

    Upstream calls `completion(...)` with no temperature, so the simulator runs at the provider's
    default and says something different every run -- two runs of one task then aren't the same
    episode, so a defended run and its no-defense baseline can't be read against each other. CaMeL's
    own turns are greedy; this makes the other half of the conversation match. (From AgentPI.)
    """

    def generate_next_message(self, messages):
        res = completion(model=self.model, custom_llm_provider=self.provider, messages=messages,
                         temperature=0.0)
        message = res.choices[0].message
        self.messages.append(message.model_dump())
        self.total_cost = res._hidden_params.get("response_cost") or 0.0
        return message.content


def point_litellm_at(model: str) -> str:
    """CaMeL names a self-hosted model ``local:<served-name>`` and reads ``LOCAL_BASE_URL`` /
    ``LOCAL_API_KEY``. tau-bench's user simulator goes through litellm's ``completion(...)``, which
    takes no base_url -- it reads process-wide ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``. So for a
    ``local:`` model we export those and return the bare served name; a hosted model is returned
    unchanged (litellm finds its own key)."""
    if not model.startswith("local:"):
        return model
    base_url = os.getenv("LOCAL_BASE_URL", "http://localhost:8000/v1")
    api_key = os.getenv("LOCAL_API_KEY", "EMPTY")
    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_KEY"] = api_key
    served = model.split(":", 1)[1]
    log.info("taubench: litellm -> %s (model %s)", base_url, served)
    return served


def catalog_configs(doomarena_root: str, domain: str, task_index: int,
                    name: str = "malicious_catalog_fixed"):
    """DoomArena's catalog attack for this task -- only the ``type: database`` (tool-output)
    components, which poison a product record's `name` for the duration of one `get_product_details`.

    The `type: user` components are dropped in code (outside this threat model), which also makes
    DoomArena's mixed `combined_retail_attack.yaml` safe to point at. Raises if the yaml has no
    database component (e.g. an airline/user-only attack)."""
    path = pathlib.Path(doomarena_root) / _CONFIG_DIR / CATALOG_CONFIGS.get(name, name)
    spec = yaml.safe_load(path.read_text())
    components = [c for c in spec["attackable_components"]
                 if c["attackable_component"].get("type") == "database"]
    if not components:
        raise ValueError(f"{path.name} has no database (tool-output) component; user-channel attacks "
                         "are out of this adapter's threat model")
    attacks = spec["attacks"][:len(components)]
    return fetch_attack_configs(components, attacks, domain, task_index)


def build_env(domain: str, task_index: int, *, run_attack: bool, attack: str, doomarena_root: str,
              user_model: str, user_provider: str):
    """A tau-bench env for one retail task, greedy user simulator, optionally wrapped by DoomArena's
    catalog attack gateway. Returns ``(env, injection_names)``.

    The gateway is itself an env wrapper (it poisons a product record during `get_product_details`),
    and CaMeL's own guard wraps whatever this returns -- see ``camel_agent.CaMeLTauBenchAgent``.
    """
    env = get_env(domain, user_strategy="llm", user_model=point_litellm_at(user_model),
                  task_split="test", user_provider=user_provider, task_index=task_index)
    env.user = DeterministicUser(model=env.user.model, provider=env.user.provider)
    injection_names: list[str] = []
    if run_attack:
        cfgs = catalog_configs(doomarena_root, domain, task_index, attack)
        injection_names = [c.attack.attack_name for c in cfgs]
        # user=None: only DATABASE components are in scope (that arg is where DoomArena swaps in an
        # adversarial user simulator, which this threat model excludes).
        env = TauBenchAttackGateway(env=env, user=None, task_name=f"user_task_{task_index}",
                                    attack_configs=cfgs)
    return env, injection_names
