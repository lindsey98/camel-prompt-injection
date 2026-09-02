"""Stateful environment for the faithful financial domain.

``FinancialEnv`` is an AgentDojo ``TaskEnvironment`` (pydantic model) so it plugs straight into
``FunctionsRuntime.run_function`` and CaMeL. Tools mutate the sub-states in place, so success/attack
is measured by the resulting state (transactions), not string matching.
"""

from pydantic import BaseModel
from agentdojo.functions_runtime import TaskEnvironment


class Transaction(BaseModel):
    source: str
    destination: str
    amount: float
    subject: str


class BankState(BaseModel):
    accounts: dict[str, float]          # account_id -> balance
    transactions: list[Transaction] = []


class MarketState(BaseModel):
    # sector -> market-data text. This text is what get_market_data returns; the OPI injection is
    # seeded INTO it (a compromised data source), so CaMeL sees the injection as an untrusted tool result.
    data: dict[str, str]


class FinancialEnv(TaskEnvironment):
    bank: BankState
    market: MarketState
    client_account: str                 # the user's own account (trusted, from the user prompt)
    attacker_account: str               # attacker-controlled account (for scoring only)


def make_financial_env(case) -> FinancialEnv:
    """Build a fresh env for one case. ``case`` is a ``tasks.FinancialCase``."""
    accounts = {
        case.client_account: 500_000.0,     # the user has funds
        case.legit_recipient: 0.0,
        case.attacker_account: 0.0,
    }
    # The compromised market-data source: legitimate text with the injected instruction appended.
    market_text = f"{case.market_text} {case.injection}"
    return FinancialEnv(
        bank=BankState(accounts=accounts, transactions=[]),
        market=MarketState(data={case.sector: market_text}),
        client_account=case.client_account,
        attacker_account=case.attacker_account,
    )
