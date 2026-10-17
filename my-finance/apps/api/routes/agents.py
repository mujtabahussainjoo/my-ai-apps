"""Read AI reviews or request an authenticated analysis without trading."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from src.agents.supervisor.agent import Supervisor
from src.database.repositories.agent_repo import AgentRepository
from src.schemas.market import Ticker

from apps.api.dependencies import ApiKeyDep, CandlesDep, PortfolioDep, SessionDep, SettingsDep, SignalsDep

router = APIRouter(prefix="/agents", tags=["agents"])


class AnalysisRequest(BaseModel):
    signal_id: str


@router.get("/reviews")
def reviews(session: SessionDep, limit: int = Query(30, ge=1, le=100)):
    return {"reviews": AgentRepository(session).recent(limit)}


@router.post("/analyse")
def analyse(
    body: AnalysisRequest,
    auth: ApiKeyDep,
    settings: SettingsDep,
    session: SessionDep,
    signals: SignalsDep,
    portfolio: PortfolioDep,
    candles: CandlesDep,
):
    signal = signals.get(body.signal_id)
    if signal is None:
        raise HTTPException(404, "Signal not found")
    rows = candles.latest(signal.symbol, signal.timeframe)
    latest = rows[0] if rows else None
    ticker = Ticker(symbol=signal.symbol, last=latest.close, timestamp=latest.timestamp) if latest else None
    supervisor = Supervisor(settings)
    result = supervisor.analyse(
        signal, ticker=ticker, portfolio=portfolio.build_snapshot(settings.trading_mode), session=session
    )
    session.commit()
    return {"approved": supervisor.approved(result), "analysis": result.model_dump(mode="json")}
