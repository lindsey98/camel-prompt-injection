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

"""Security policies for the AgentDyn suites (shopping, github, dailylife).

AgentDyn (https://github.com/SaFo-Lab/AgentDyn) is a fork of the ``agentdojo``
package that adds three suites on top of the original four. The three suites
share most of their tools (email, filesystem, web, calendar, banking clients),
so the policies for the shared tools live in a common base engine and each
suite engine adds its platform-specific tools.

This module imports cleanly under vanilla agentdojo too: the engines don't need
the AgentDyn environment classes, and ``AGENTDYN_DATETIME_ENVIRONMENTS`` is
empty when the fork is not installed.
"""

from collections.abc import Mapping

from src.camel import security_policy
from src.camel.capabilities import can_readers_read_value, is_public, is_trusted
from src.camel.interpreter.value import CaMeLList, CaMeLNone, CaMeLValue
from src.camel.pipeline_elements.security_policies.agentdojo_security_policies import (
    AgentDojoSecurityPolicyEngine,
)
from src.camel.security_policy import Allowed, Denied, SecurityPolicyResult

try:  # Only available when the AgentDyn fork of agentdojo is installed
    from agentdojo.default_suites.v1.dailylife.task_suite import DailyLifeEnvironment
    from agentdojo.default_suites.v1.github.task_suite import GithubEnvironment
    from agentdojo.default_suites.v1.shopping.task_suite import ShoppingEnvironment

    AGENTDYN_AVAILABLE = True
    # Suites whose tasks need the datetime classes in the interpreter namespace
    # (shopping and dailylife include the calendar tools; github does not).
    AGENTDYN_DATETIME_ENVIRONMENTS: tuple[type, ...] = (ShoppingEnvironment, DailyLifeEnvironment)
except ImportError:
    AGENTDYN_AVAILABLE = False
    AGENTDYN_DATETIME_ENVIRONMENTS = ()


# Read-only tools shared by the AgentDyn suites.
_SHARED_NO_SIDE_EFFECT_TOOLS = {
    # Email tools (dynamic_email_client)
    "get_unread_emails",
    "get_received_emails",
    "get_sent_emails",
    "get_draft_emails",
    "search_emails",
    "search_contacts_by_name",
    "search_contacts_by_email",
    # Calendar tools (dynamic_calendar_client)
    "get_current_day",
    "get_day_calendar_events",
    "search_calendar_events",
    # Filesystem tools (file_client)
    "list_directory",
    "read_file",
}


def _all_trusted_policy(tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
    """Allows only if every provided argument comes directly from the user."""
    untrusted = [name for name, arg in kwargs.items() if not is_trusted(arg)]
    if untrusted:
        return Denied(f"Arguments {untrusted} of {tool_name} do not come directly from the user.")
    return Allowed()


def _allow_policy(tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
    """For side-effectful tools whose effects stay in state only the user can read."""
    return Allowed()


def _public_or_trusted(kwargs: Mapping[str, CaMeLValue], *arg_names: str) -> SecurityPolicyResult:
    """Requires each present argument to be public or to come from the user.

    Used for data sent to the (public) web, where there is no meaningful
    recipient set to check readers against.
    """
    for name in arg_names:
        if name not in kwargs:
            continue
        arg = kwargs[name]
        if isinstance(arg, CaMeLNone):
            continue
        if not is_trusted(arg) and not is_public(arg):
            return Denied(f"Argument {name} is private and does not come directly from the user.")
    return Allowed()


class AgentDynBaseSecurityPolicyEngine(AgentDojoSecurityPolicyEngine):
    """Policies for the tools shared by all AgentDyn suites."""

    def __init__(self, env) -> None:
        super().__init__(env)
        self.policies = [
            # Email
            ("send_email", self.send_email_policy),
            ("delete_email", self.delete_email_policy),
            # Calendar (sends emails to participants)
            ("create_calendar_event", self.create_calendar_event_policy),
            ("cancel_calendar_event", self.cancel_calendar_event_policy),
            ("reschedule_calendar_event", self.reschedule_calendar_event_policy),
            ("add_calendar_event_participants", self.add_calendar_event_participants_policy),
            # Filesystem: local state that only the user can read.
            ("create_file", _allow_policy),
            ("create_dir", _allow_policy),
            ("copy_node", _allow_policy),
            ("move_node", self.move_node_policy),
            ("delete_node", self.delete_node_policy),
            # Web: URLs and form data are revealed to the (public) web.
            ("browse_webpage", self.browse_webpage_policy),
            ("input_to_webpage", self.input_to_webpage_policy),
            ("download_file_through_url", self.browse_webpage_policy),
            ("download_file_through_id", self.download_file_through_id_policy),
            # Money
            ("send_money", self.send_money_policy),
        ]
        self.no_side_effect_tools = security_policy.NO_SIDE_EFFECT_TOOLS | _SHARED_NO_SIDE_EFFECT_TOOLS

    # --- Email ---

    def send_email_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        # Same rationale as the workspace suite: either the recipients come from the
        # user, or every recipient must be allowed to read every part of the email.
        recipients: CaMeLList = kwargs["recipients"]  # type: ignore
        if "cc" in kwargs and isinstance(kwargs["cc"], CaMeLList):
            recipients = recipients.add(kwargs["cc"])
        if "bcc" in kwargs and isinstance(kwargs["bcc"], CaMeLList):
            recipients = recipients.add(kwargs["bcc"])

        if is_trusted(recipients):
            return Allowed()
        recipients_set = set(recipients.raw)

        for field in ("body", "subject", "attachments"):
            if field not in kwargs or isinstance(kwargs[field], CaMeLNone):
                continue
            if not can_readers_read_value(recipients_set, kwargs[field]):
                return Denied(f"The {field} is not public or shared with the recipients: recipients={recipients_set}.")
        return Allowed()

    def delete_email_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        if not is_trusted(kwargs["email_id"]):
            return Denied("The email to be deleted does not come directly from the user.")
        return Allowed()

    # --- Calendar ---

    def create_calendar_event_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        # The event details are emailed to the participants, so either the participants
        # come from the user or they must be able to read all the event details.
        participants = kwargs.get("participants")
        if participants is None or isinstance(participants, CaMeLNone) or is_trusted(participants):
            return Allowed()
        participants_set = set(participants.raw)
        for field in ("title", "description", "location", "start_time", "end_time"):
            if field not in kwargs or isinstance(kwargs[field], CaMeLNone):
                continue
            if not can_readers_read_value(participants_set, kwargs[field]):
                return Denied(f"The {field} is not public or shared with the participants.")
        return Allowed()

    def cancel_calendar_event_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        if not is_trusted(kwargs["event_id"]):
            return Denied("The event to be canceled does not come directly from the user.")
        return Allowed()

    def reschedule_calendar_event_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        # The new times are emailed to the event participants.
        try:
            event_id = kwargs["event_id"].raw
            event_participants = set(self._env.calendar.events[event_id].participants)  # type: ignore[attr-defined]
        except Exception:
            # Can't resolve the participants: fall back to requiring user-provided args.
            return _all_trusted_policy(tool_name, kwargs)
        for field in ("new_start_time", "new_end_time"):
            if field not in kwargs or isinstance(kwargs[field], CaMeLNone):
                continue
            if not can_readers_read_value(event_participants, kwargs[field]):
                return Denied(f"The {field} is not readable by the participants of the event.")
        return Allowed()

    def add_calendar_event_participants_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        # The new participants receive the event data, which we can't inspect: require
        # the event to be user-chosen (same rationale as the workspace suite).
        if not is_trusted(kwargs["event_id"]):
            return Denied("The event does not come directly from the user.")
        return Allowed()

    # --- Filesystem ---

    def delete_node_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        if not is_trusted(kwargs["path"]):
            return Denied("The path to be deleted does not come directly from the user.")
        return Allowed()

    def move_node_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        # Moving removes the source node, so treat it like a deletion of the source.
        if not is_trusted(kwargs["source_path"]):
            return Denied("The source path to be moved does not come directly from the user.")
        return Allowed()

    # --- Web ---

    def browse_webpage_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        # Visiting a URL reveals the URL to the web, and in AgentDyn it can also
        # trigger the page's server-side action ("clicking" a link).
        return _public_or_trusted(kwargs, "url")

    def download_file_through_id_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        return _public_or_trusted(kwargs, "file_id")

    def input_to_webpage_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        # Submitting a form sends the values to the website: everything must be
        # public or come directly from the user.
        return _public_or_trusted(kwargs, "url", "input_ids", "input_values")

    # --- Money ---

    def send_money_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        # Same rationale as the banking suite: the recipient must come from the user,
        # and must be able to read all the transaction details.
        recipient = kwargs["recipient"]
        if not is_trusted(recipient):
            return Denied("The recipient does not come directly from the user.")
        recipients_set = {recipient.raw}
        for field in ("subject", "amount", "date"):
            if field not in kwargs or isinstance(kwargs[field], CaMeLNone):
                continue
            if not can_readers_read_value(recipients_set, kwargs[field]):
                return Denied(f"The recipient can't read the transaction {field}.")
        return Allowed()


shopping_no_side_effect_tools = {
    "get_balance",
    "get_shopping_account_user_information",
    "get_shopping_linked_unread_emails",
    "get_shopping_linked_received_emails",
    "search_product",
    "view_order_history",
    "get_invoice",
    "view_cart",
    "cart_total",
    "view_available_discounts",
    # The OTP is read from an email by design, so it can never be "trusted"; the
    # action being verified is gated by its own policy instead.
    "verify_shopping_account",
}


class ShoppingSecurityPolicyEngine(AgentDynBaseSecurityPolicyEngine):
    def __init__(self, env) -> None:
        super().__init__(env)
        self.policies = [
            *self.policies,
            # Credentials and account data must come from the user.
            ("login_shopping_account", _all_trusted_policy),
            ("update_shopping_account_password", _all_trusted_policy),
            ("update_shopping_account_user_info", _all_trusted_policy),
            # The cart is local state; checkout is the gate that spends money.
            ("cart_add_product", _allow_policy),
            ("cart_remove_product", _allow_policy),
            ("clear_cart", _allow_policy),
            ("checkout_selected_cart", _all_trusted_policy),
            ("refund_order", self.refund_order_policy),
        ]
        self.no_side_effect_tools = self.no_side_effect_tools | shopping_no_side_effect_tools

    def refund_order_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        if not is_trusted(kwargs["order_id"]):
            return Denied("The order to be refunded does not come directly from the user.")
        return Allowed()


github_no_side_effect_tools = {
    "get_github_linked_unread_emails",
    "get_logged_in_github_user_information",
    "get_github_account_user_information",
    "get_github_repository_information",
    "git_get_linked_ssh_keys",
    # The OTP is read from an email by design, so it can never be "trusted"; the
    # action being verified is gated by its own policy instead.
    "verify_github_account",
}


class GithubSecurityPolicyEngine(AgentDynBaseSecurityPolicyEngine):
    def __init__(self, env) -> None:
        super().__init__(env)
        self.policies = [
            *self.policies,
            # Credentials and account-security data must come from the user.
            ("login_github_account", _all_trusted_policy),
            ("update_github_account_password", _all_trusted_policy),
            ("git_add_ssh_key", _all_trusted_policy),
            ("git_delete_ssh_key", _all_trusted_policy),
            # Repository management
            ("git_create_repo", _allow_policy),
            ("git_delete_repo", self.git_delete_repo_policy),
            ("git_transfer_repo_ownership", _all_trusted_policy),
            ("git_invite_collaborators", _all_trusted_policy),
            # Local-only effects
            ("git_clone", _allow_policy),
            ("git_pull", _allow_policy),
            ("git_star", _allow_policy),
            ("git_unstar", _allow_policy),
            # Publishing content
            ("git_push", self.git_push_policy),
            ("git_issue", self.git_issue_policy),
        ]
        self.no_side_effect_tools = self.no_side_effect_tools | github_no_side_effect_tools

    def git_delete_repo_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        if not is_trusted(kwargs["repo_name"]):
            return Denied("The repository to be deleted does not come directly from the user.")
        return Allowed()

    def git_push_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        # Pushing publishes local files to the remote repository. We can't inspect the
        # file contents, so require the pushed path to be user-chosen.
        if not is_trusted(kwargs["local_path"]):
            return Denied("The path to be pushed does not come directly from the user.")
        return Allowed()

    def git_issue_policy(self, tool_name: str, kwargs: Mapping[str, CaMeLValue]) -> SecurityPolicyResult:
        # Issues are visible to everybody watching the repository.
        return _public_or_trusted(kwargs, "repo_name", "title", "comment_body")


dailylife_no_side_effect_tools = {
    "get_balance",
    # Confirms a pending transaction with an OTP read from an email: the OTP can
    # never be "trusted", and the transaction itself is gated by send_money's policy.
    "verify_transaction",
}


class DailyLifeSecurityPolicyEngine(AgentDynBaseSecurityPolicyEngine):
    def __init__(self, env) -> None:
        super().__init__(env)
        self.no_side_effect_tools = self.no_side_effect_tools | dailylife_no_side_effect_tools


AGENTDYN_SECURITY_POLICY_ENGINES: dict[str, type[AgentDojoSecurityPolicyEngine]] = {
    "shopping": ShoppingSecurityPolicyEngine,
    "github": GithubSecurityPolicyEngine,
    "dailylife": DailyLifeSecurityPolicyEngine,
}
