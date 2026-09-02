"""CaMeL security policy for the faithful financial domain (modeled on banking.py).

The one side-effecting tool, ``transfer_funds``, is allowed only if its ``account_id``, ``amount``
and ``destination`` come **directly from the user** (are ``is_trusted``). A transfer whose args flow
from the untrusted market-data result is denied. The read tools are side-effect-free and always
allowed. This is real capability tracking: the SAME tool is allowed for a user-authorized transfer
and denied for the injected one -- a tool-name allowlist cannot make that distinction.
"""

from src.camel.pipeline_elements.security_policies.agentdojo_security_policies import (
    AgentDojoSecurityPolicyEngine,
    make_trusted_fields_policy,
)
from src.camel.security_policy import NO_SIDE_EFFECT_TOOLS

_READ_ONLY = {"get_market_data", "get_account_balance", "get_portfolio"}


class FinancialSecurityPolicyEngine(AgentDojoSecurityPolicyEngine):
    def __init__(self, env) -> None:
        super().__init__(env)
        self.policies = [
            # A transfer's source, amount and destination must come from the user, not from a tool
            # result -- mirrors banking.py's send_money_policy (recipient must be user-provided).
            ("transfer_funds", make_trusted_fields_policy(("account_id", "amount", "destination"))),
        ]
        self.no_side_effect_tools = NO_SIDE_EFFECT_TOOLS | _READ_ONLY
