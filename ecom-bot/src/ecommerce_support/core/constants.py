"""Shared numeric constants that must agree across layers.

The embedding dimension is fixed at the database schema level (``document_chunks.embedding`` is a
``vector(1536)``); ingestion must reject any embedding whose length differs (FR-036). Keeping the
value in one place lets the DB model, the embedding adapters, and validation all agree.
"""

from __future__ import annotations

EMBEDDING_DIMENSIONS = 1536

RETURN_WINDOW_DAYS = 30
"""Days after delivery during which an order is return-eligible (FR-039).

Business policy, not a tunable system setting: real commerce backends own this rule, and the
mock/fixture adapter mirrors a 30-day window so return-eligibility answers stay deterministic.
"""
