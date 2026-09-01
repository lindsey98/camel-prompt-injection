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

"""Compare the per-task `utility` of two runs (pipelines) and list the differences.

Typical use: find which tasks pass without the defense but fail with CaMeL
(regressions), in the no-attack setting.

Usage:
    python compare_utility.py <baseline_pipeline> <camel_pipeline> [--logdir logs] [--attack none]

Example:
    python compare_utility.py Llama-3.3-70B-Instruct Llama-3.3-70B-Instruct+camel
"""

import argparse
import json
from pathlib import Path


def load_utilities(logdir: Path, pipeline: str, attack: str) -> dict[tuple[str, str], bool]:
    """Maps (suite_name, user_task_id) -> utility for one pipeline.

    Reads logs/<pipeline>/<suite>/<user_task>/<attack>/<injection>.json. For the
    no-attack setting both <attack> and <injection> are "none".
    """
    results: dict[tuple[str, str], bool] = {}
    base = logdir / pipeline
    if not base.is_dir():
        raise SystemExit(f"No logs found for pipeline '{pipeline}' at {base}")
    for json_path in base.glob(f"*/user_task_*/{attack}/*.json"):
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        suite = data.get("suite_name", json_path.parts[-4])
        task = data.get("user_task_id", json_path.parts[-3])
        results[(suite, task)] = bool(data.get("utility", False))
    return results


def _task_sort_key(item: tuple[str, str]) -> tuple[str, int, str]:
    suite, task = item
    # sort user_task_10 after user_task_2
    num = task.removeprefix("user_task_")
    return (suite, int(num)) if num.isdigit() else (suite, 1_000_000, task)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_pipeline", help="e.g. Llama-3.3-70B-Instruct (the --use-original run)")
    parser.add_argument("camel_pipeline", help="e.g. Llama-3.3-70B-Instruct+camel")
    parser.add_argument("--logdir", default="logs", type=Path)
    parser.add_argument("--attack", default="none", help="attack subfolder name (default: none = no attack)")
    args = parser.parse_args()

    baseline = load_utilities(args.logdir, args.baseline_pipeline, args.attack)
    camel = load_utilities(args.logdir, args.camel_pipeline, args.attack)

    common = sorted(baseline.keys() & camel.keys(), key=_task_sort_key)
    only_baseline = baseline.keys() - camel.keys()
    only_camel = camel.keys() - baseline.keys()

    regressions = [k for k in common if baseline[k] and not camel[k]]
    improvements = [k for k in common if not baseline[k] and camel[k]]
    both_pass = [k for k in common if baseline[k] and camel[k]]
    both_fail = [k for k in common if not baseline[k] and not camel[k]]

    print(f"Comparing {len(common)} tasks present in both runs (attack={args.attack})")
    print(f"  baseline pipeline: {args.baseline_pipeline}")
    print(f"  camel pipeline:    {args.camel_pipeline}\n")

    print(f"REGRESSED (baseline pass -> camel FAIL): {len(regressions)}")
    for suite, task in regressions:
        print(f"  [{suite}] {task}")

    print(f"\nimproved (baseline fail -> camel pass): {len(improvements)}")
    for suite, task in improvements:
        print(f"  [{suite}] {task}")

    print(
        f"\nsummary: both_pass={len(both_pass)} both_fail={len(both_fail)} "
        f"regressed={len(regressions)} improved={len(improvements)}"
    )
    if only_baseline:
        print(f"note: {len(only_baseline)} tasks only in baseline (not run with camel)")
    if only_camel:
        print(f"note: {len(only_camel)} tasks only in camel (not run with baseline)")

    # Per-suite regression counts (where the damage concentrates)
    by_suite: dict[str, list[int]] = {}
    for (suite, _), passed_b, passed_c in (
        (k, baseline[k], camel[k]) for k in common
    ):
        counts = by_suite.setdefault(suite, [0, 0])  # [regressed, total]
        counts[1] += 1
        if passed_b and not passed_c:
            counts[0] += 1
    print("\nregressions per suite:")
    for suite in sorted(by_suite):
        regressed, total = by_suite[suite]
        print(f"  {suite}: {regressed}/{total}")


if __name__ == "__main__":
    main()
