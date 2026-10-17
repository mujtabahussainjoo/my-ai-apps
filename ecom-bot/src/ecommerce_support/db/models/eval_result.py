"""Evaluation result persistence (DATA-001 ``eval_results``; FR-055)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import CreatedAtMixin


class EvalResult(Base, CreatedAtMixin):
    """A single metric observation for an evaluation case."""

    __tablename__ = "eval_results"
    __table_args__ = (Index("ix_eval_results_dataset_metric", "dataset_version", "metric"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
