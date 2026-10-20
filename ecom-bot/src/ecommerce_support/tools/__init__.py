"""Typed tool layer: registry, permission checks, and audit hooks (FR-027, SEC-010).

Tools expose commerce/RAG capabilities to agents. The registry validates arguments, enforces
per-agent allowlists and authentication, and emits redacted audit events. Tools are plain Python
(no LangChain/LangGraph imports) so they test without framework runtime.
"""

from ecommerce_support.tools.account import (
    GetAccountSummaryTool,
    GetProfileTool,
    create_account_registry,
)
from ecommerce_support.tools.audit import AuditHook, LoggingAuditHook, RecordingAuditHook
from ecommerce_support.tools.order import (
    GetOrderTool,
    ListOrdersTool,
    ReturnEligibilityTool,
    TrackShipmentTool,
    create_order_registry,
)
from ecommerce_support.tools.policy import SearchPoliciesTool, create_policy_registry
from ecommerce_support.tools.product import (
    CheckStockTool,
    GetProductTool,
    SearchProductsTool,
    create_product_registry,
)
from ecommerce_support.tools.registry import Tool, ToolRegistry, create_tool_registry

__all__ = [
    "AuditHook",
    "CheckStockTool",
    "GetAccountSummaryTool",
    "GetOrderTool",
    "GetProductTool",
    "GetProfileTool",
    "ListOrdersTool",
    "LoggingAuditHook",
    "RecordingAuditHook",
    "ReturnEligibilityTool",
    "SearchPoliciesTool",
    "SearchProductsTool",
    "Tool",
    "ToolRegistry",
    "TrackShipmentTool",
    "create_account_registry",
    "create_order_registry",
    "create_policy_registry",
    "create_product_registry",
    "create_tool_registry",
]
