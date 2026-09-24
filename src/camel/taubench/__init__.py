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

"""Run CaMeL on tau-bench (retail) under DoomArena's malicious_catalog_fixed attack.

This adapter bridges CaMeL's single-shot code-gen + interpreter to tau-bench's multi-turn,
user-simulator conversation. See ``camel_agent.py`` for the per-turn loop and ``retail_policy.py``
for the CaMeL security policy that enforces the defense.

Requires (not on PyPI, install on the run host, mirroring AgentPI):
    uv pip install "git+https://github.com/sierra-research/tau-bench.git#egg=tau_bench"
    uv pip install -e <DoomArena>/doomarena/core
    uv pip install -e <DoomArena>/doomarena/taubench
"""

# Warm up agentdojo's suite machinery FIRST. `privileged_llm` (pulled in via camel_agent) imports
# `agentdojo.default_suites.v1.banking.task_suite` directly; doing that before `agentdojo.task_suite`
# is initialized re-enters the half-loaded `banking` package through `load_suites` and raises
# "cannot import name 'banking_task_suite' ... circular import". Importing the task-suite package here
# (as main.py does implicitly) forces the working order. Must run before any camel_agent import.
import agentdojo.task_suite  # noqa: E402,F401

