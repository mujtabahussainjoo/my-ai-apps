"""Integrations: commerce and ticketing adapters behind stable interfaces (FR-041, INT-003/004).

v1 ships mock/fixture implementations; real backends (Magento/Adobe Commerce, Jira, ServiceNow)
are documented extension points implemented behind the same interfaces.
"""

from __future__ import annotations

from ecommerce_support.integrations.account import AccountAdapter
from ecommerce_support.integrations.commerce import CommerceAdapter
from ecommerce_support.integrations.jira import JiraTicketingAdapter, build_jira_payload
from ecommerce_support.integrations.memory_account import InMemoryAccountAdapter
from ecommerce_support.integrations.memory_commerce import InMemoryCommerceAdapter
from ecommerce_support.integrations.servicenow import (
    ServiceNowTicketingAdapter,
    build_servicenow_payload,
)
from ecommerce_support.integrations.sql_account import SqlAccountAdapter
from ecommerce_support.integrations.sql_commerce import (
    SqlCommerceAdapter,
    decide_return_eligibility,
)
from ecommerce_support.integrations.ticketing import (
    MockTicketingAdapter,
    TicketingAdapter,
    build_ticket_description,
    create_ticketing_adapter,
)

__all__ = [
    "AccountAdapter",
    "CommerceAdapter",
    "InMemoryAccountAdapter",
    "InMemoryCommerceAdapter",
    "JiraTicketingAdapter",
    "MockTicketingAdapter",
    "ServiceNowTicketingAdapter",
    "SqlAccountAdapter",
    "SqlCommerceAdapter",
    "TicketingAdapter",
    "build_jira_payload",
    "build_servicenow_payload",
    "build_ticket_description",
    "create_ticketing_adapter",
    "decide_return_eligibility",
]
