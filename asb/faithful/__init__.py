"""Faithful (typed + stateful) re-engineering of ASB's financial domain.

ASB's stock tools are parameterless mocks with no state, so CaMeL degenerates to a tool-name
allowlist. This package rebuilds the financial_analyst domain as a small AgentDojo-style suite:
a stateful ``FinancialEnv``, typed tools (``financial_tools``), per-tool CaMeL policies modeled on
banking (``financial_policy``), hand-built (task, injection) cases (``tasks``), and a runner
(``run_financial``) that scores baseline vs CaMeL by real environment state.

The point: the OPI injection lives in an untrusted tool result (market data), and the attack is a
``transfer_funds`` to an attacker account whose args come from that untrusted data. CaMeL denies it
by capability tracking while still allowing the benign, user-authorized transfer — something a plain
allowlist cannot distinguish.
"""
