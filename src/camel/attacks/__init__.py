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

"""Custom AgentDojo attacks. Importing this package registers them with AgentDojo's attack registry.

ChatInject is intentionally NOT registered here: it now lives in the agentdojo fork
(https://github.com/lindsey98/agentdojo, `agentdojo.attacks.chat_inject`), which is the up-to-date
source. Registering a second copy here would silently override the fork's (register_attack just does
`ATTACKS[name] = attack`), so we defer to the fork.
"""

from src.camel.attacks import cascade  # noqa: F401  -- import for @register_attack side effects
from src.camel.attacks import cascade_adaptive  # noqa: F401  -- import for @register_attack side effects

__all__ = ["cascade", "cascade_adaptive"]
