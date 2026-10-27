import argparse
import glob
import json
import os
import re

import threat_model as tm

# DEFAULT_SUITES = ["banking", "slack", "travel", "workspace"]
DEFAULT_SUITES = ["github", "shopping", "dailylife"]


def run_dir_name(model: str) -> str:
    """Mirror agentdojo's make_run_name: basename + '+progent' when Progent is on."""
    name = model.split("/")[-1]
    # name += "+camel"
    # name += "+camel+secpol"
    return name


def _task_of(path: str) -> str:
    """The user_task_* component of a record path (…/<suite>/user_task_N/<attack>/<inj>.json)."""
    m = re.search(r"(user_task_\d+)", path)
    return m.group(1) if m else ""


def summarize(log_dir: str, name: str, attack, suites, task_filter: str):
    """task_filter: 'inscope' | 'none'. 'inscope' counts only tasks the trust-separation threat model
    admits (see threat_model.py -- payload separable from the task's trusted content); 'none' counts
    every task (AgentDojo's full set)."""
    results = {}
    for suite in suites:
        if attack is None:
            pattern = f"{log_dir}/{name}/{suite}/user_task_*/none/none.json"
        else:
            pattern = f"{log_dir}/{name}/{suite}/user_task_*/{attack}/injection_task_*.json"
        files = glob.glob(pattern)
        if not files:
            continue
        allow = None if task_filter == "none" else tm.qualifying_tasks(suite)
        utility_scores, security_scores, kept_tasks = [], [], set()
        for f in files:
            if allow is not None and _task_of(f) not in allow:
                continue
            with open(f) as fp:
                data = json.load(fp)
            kept_tasks.add(_task_of(f))
            if "utility" in data:
                utility_scores.append(data["utility"])
            if "security" in data:
                security_scores.append(data["security"])
        if allow is not None and not kept_tasks:
            continue
        results[suite] = {
            "utility": sum(utility_scores) / len(utility_scores) if utility_scores else "N/A",
            "security": sum(security_scores) / len(security_scores) if security_scores else "N/A",
            "n_tasks": len(kept_tasks),
            "n_total": len({_task_of(f) for f in files}),
        }
    return results


def print_table(title: str, results: dict, task_filter: str):
    print(f"\n=== {title}{f'  [filter: {task_filter}]' if task_filter != 'none' else ''} ===")
    if not results:
        print("(no logs found)")
        return
    print(f"{'Suite':<12} {'Tasks':>7} {'Utility':>8} {'Security':>10}")
    print("-" * 40)
    for suite, scores in results.items():
        tasks = f"{scores['n_tasks']}/{scores['n_total']}"
        print(f"{suite:<12} {tasks:>7} {str(scores['utility'])[:6]:>8} {str(scores['security'])[:6]:>10}")
    u = [v["utility"] for v in results.values() if isinstance(v["utility"], float)]
    s = [v["security"] for v in results.values() if isinstance(v["security"], float)]
    print("-" * 40)
    line = f"{'avg':<12} {'':>7}"
    if u:
        line += f" {sum(u) / len(u):>8.3f}"
    if s:
        line += f" {sum(s) / len(s):>10.3f}"
    print(line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarize AgentDojo results (utility/security per suite).")
    parser.add_argument("--model", default="gpt-4o-mini",
                        help="Model id; basename and the +progent suffix are applied automatically.")
    parser.add_argument("--name", default=None,
                        help="Exact run-directory name under --log-dir (overrides --model).")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--suites", nargs="+", default=DEFAULT_SUITES,
                        help="Suites to summarize (e.g. shopping github dailylife for AgentDyn).")
    parser.add_argument("--filter", choices=("inscope", "none"), default="inscope",
                        help="inscope: count only tasks the trust-separation threat model admits "
                             "(payload separable from the task's trusted content); none: all tasks. "
                             "Applies only under attack; utility is always measured over the full set.")
    args = parser.parse_args()

    name = args.name or run_dir_name(args.model)
    print(f"Results for: {name}")

    # Utility (no attack) is a benign-capability metric, unrelated to injection co-location, so it is
    # always measured over the full task set; the threat-model filter applies only under attack.
    def eff_filter(attack):
        return args.filter if attack is not None else "none"

    # No-attack (utility) and under-attack (utility + security).
    for attack, title in [(None, "No attack"), ("important_instructions", "Attack: important_instructions"),
                          ("tool_knowledge", "Attack: tool_knowledge")
                          ]:
        print_table(title, summarize(args.log_dir, name, attack, args.suites, eff_filter(attack)),
                    eff_filter(attack))
