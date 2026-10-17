"""Evaluation result repository (FR-055)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import EvalResult as EvalRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import EvalResult, EvalResultCreate


def _to_result(row: EvalRow) -> EvalResult:
    return EvalResult(
        id=row.id,
        dataset_version=row.dataset_version,
        case_id=row.case_id,
        metric=row.metric,
        score=row.score,
        detail=dict(row.detail),
        created_at=row.created_at,
    )


class EvalResultRepository(BaseRepository):
    """Persist evaluation metric observations for reporting."""

    async def record_many(self, results: Sequence[EvalResultCreate]) -> int:
        for result in results:
            self.session.add(
                EvalRow(
                    id=new_id("eval"),
                    dataset_version=result.dataset_version,
                    case_id=result.case_id,
                    metric=result.metric,
                    score=result.score,
                    detail=dict(result.detail),
                )
            )
        await self.session.flush()
        return len(results)

    async def list_by_dataset(
        self, dataset_version: str, *, metric: str | None = None
    ) -> list[EvalResult]:
        conditions = [EvalRow.dataset_version == dataset_version]
        if metric is not None:
            conditions.append(EvalRow.metric == metric)
        stmt = (
            select(EvalRow).where(*conditions).order_by(EvalRow.case_id.asc(), EvalRow.metric.asc())
        )
        return [_to_result(row) for row in (await self.session.scalars(stmt)).all()]
