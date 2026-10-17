"""Signals, strategies, and the promotion gate.

The qualification endpoint is the most consequential route in this file. It is
separated from the seed path, requires a named operator, and refuses to promote
a strategy that has no evidence attached - because "qualified" is the one word
in this system that lets real money move.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from src.core.enums import StrategyStatus
from src.database.seed import set_qualified
from src.strategies import registry as strategy_registry

from apps.api.dependencies import (
    BacktestsDep,
    OperatorDep,
    SessionDep,
    SettingsDep,
    SignalsDep,
    StrategiesDep,
)

router = APIRouter(tags=["signals"])


# ── Signals ─────────────────────────────────────────────────────────────────


@router.get("/signals")
def list_signals(
    signals: SignalsDep,
    symbol: str | None = None,
    strategy: str | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Recent signals, newest first."""
    rows = signals.recent(symbol=symbol, strategy=strategy, limit=limit)
    return {
        "count": len(rows),
        "signals": [s.model_dump(mode="json") for s in rows],
    }


@router.get("/signals/{signal_id}")
def get_signal(signals: SignalsDep, signal_id: str) -> dict[str, Any]:
    signal = signals.get(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"no signal {signal_id!r}")
    return signal.model_dump(mode="json")


# ── Strategies ──────────────────────────────────────────────────────────────


@router.get("/strategies")
def list_strategies(strategies: StrategiesDep) -> dict[str, Any]:
    """Every known strategy with its promotion state."""
    rows = strategies.all()
    by_name = {r.strategy: r for r in rows}
    out = []
    for name in strategy_registry.all_names():
        row = by_name.get(name)
        out.append(
            {
                "strategy": name,
                "status": row.status if row else StrategyStatus.CANDIDATE.value,
                "qualified": bool(row.qualified) if row else False,
                "blocking_reason": row.blocking_reason if row else "no status recorded",
                "metrics": row.metrics if row else None,
                "promoted_at": row.promoted_at.isoformat() if row and row.promoted_at else None,
            }
        )
    return {"count": len(out), "strategies": out}


@router.get("/strategies/{name}")
def get_strategy(name: str, strategies: StrategiesDep) -> dict[str, Any]:
    try:
        strategy_registry.describe()
        known = name in strategy_registry.all_names()
    except Exception:  # noqa: BLE001
        known = False
    if not known:
        raise HTTPException(
            status_code=404,
            detail=f"unknown strategy {name!r}; known: {', '.join(strategy_registry.all_names())}",
        )
    row = strategies.get(name)
    return {
        "strategy": name,
        "status": row.status if row else StrategyStatus.CANDIDATE.value,
        "qualified": bool(row.qualified) if row else False,
        "blocking_reason": row.blocking_reason if row else "no status recorded",
        "metrics": row.metrics if row else None,
        "qualification": row.qualification if row else None,
        "version": row.version if row else None,
        "tradeable": bool(row.qualified) if row else False,
    }


class QualificationRequest(BaseModel):
    """A promotion decision, with the evidence that justifies it."""

    qualified: bool
    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Why this change is justified. Stored with the decision.",
    )


@router.post("/strategies/{name}/qualification")
def set_qualification(
    name: str,
    body: QualificationRequest,
    operator: OperatorDep,
    strategies: StrategiesDep,
    backtests: BacktestsDep,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Promote or revoke a strategy.

    Promoting requires a named operator, a written reason, and at least one
    recorded backtest for that strategy. That is a deliberately high bar: it is
    still weaker than the real promotion rule (which also weighs paper
    performance), but it stops a strategy being switched on by accident.
    """
    if name not in strategy_registry.all_names():
        raise HTTPException(status_code=404, detail=f"unknown strategy {name!r}")

    evidence = None
    if body.qualified:
        runs = backtests.list_runs(strategy=name, limit=1)
        if not runs:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{name!r} has no recorded backtest, so it cannot be qualified. "
                    f"Run 'make backtest STRATEGY={name}' and review the result first."
                ),
            )
        from src.evaluation.service import evaluate_strategy

        try:
            result, _, evidence = evaluate_strategy(session, name, settings)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not result.qualified:
            raise HTTPException(
                409,
                detail={"message": "qualification criteria failed", "report": result.model_dump(mode="json")},
            )
        evidence["metrics"] = runs[0].metrics

    set_qualified(
        session,
        name,
        qualified=body.qualified,
        reason=f"{body.reason} (by {operator})",
        metrics=(evidence or {}).get("metrics") if evidence else None,
        qualification=evidence,
    )
    from src.database.repositories import SystemEventRepository

    SystemEventRepository(session).log(
        "operator",
        "qualification_changed",
        body.reason,
        context={"operator": operator, "strategy": name, "qualified": body.qualified},
    )
    strategies.session.commit()

    updated = strategies.get(name)
    return {
        "strategy": name,
        "status": updated.status,
        "qualified": bool(updated.qualified),
        "blocking_reason": updated.blocking_reason,
        "changed_by": operator,
        "reason": body.reason,
    }


@router.get("/strategies/{name}/evaluation")
def evaluation(name: str, session: SessionDep, settings: SettingsDep):
    from src.evaluation.service import evaluate_strategy

    try:
        result, paper_ready, evidence = evaluate_strategy(session, name, settings)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"qualified": result.qualified, "paper_ready": paper_ready, "evidence": evidence}


class PaperAdmission(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


@router.post("/strategies/{name}/paper-testing")
def admit_paper(
    name: str,
    body: PaperAdmission,
    operator: OperatorDep,
    session: SessionDep,
    settings: SettingsDep,
    strategies: StrategiesDep,
):
    from src.evaluation.service import evaluate_strategy

    if name not in strategy_registry.all_names():
        raise HTTPException(404, "Unknown strategy")
    try:
        result, ready, evidence = evaluate_strategy(session, name, settings)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not ready:
        raise HTTPException(
            409, detail={"message": "backtest criteria failed", "report": result.model_dump(mode="json")}
        )
    strategies.set(
        name,
        StrategyStatus.PAPER_TESTING.value,
        qualified=False,
        qualification={**evidence, "operator": operator, "reason": body.reason},
        blocking_reason="Paper testing admitted; live qualification pending",
    )
    session.commit()
    return {"strategy": name, "status": "paper_testing", "qualified": False, "operator": operator}


__all__ = ["router"]
