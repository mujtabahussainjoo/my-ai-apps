"""Persist the evidence and structured result of every AI review."""

from sqlalchemy import select

from src.core.security import redact
from src.database.base import utcnow
from src.database.models.audit import AgentMessage, AgentSession


class AgentRepository:
    def __init__(self, session):
        self.session = session

    def record(self, state):
        row = AgentSession(
            agent="supervisor", symbol=state.symbol, session_type="analysis", status="completed"
        )
        self.session.add(row)
        self.session.flush()
        payload = redact(state.model_dump(mode="json"))
        decision = state.assessments.get("decision")
        self.session.add(
            AgentMessage(
                session_id=row.id,
                role="assistant",
                content=decision.summary if decision else "Review incomplete",
                structured=payload,
                blocked=bool(state.errors),
                created_at=utcnow(),
            )
        )
        self.session.flush()
        return row.id

    def recent(self, limit=50):
        rows = self.session.scalars(
            select(AgentMessage).order_by(AgentMessage.created_at.desc()).limit(limit)
        )
        return [
            {
                "session_id": row.session_id,
                "summary": row.content,
                "analysis": row.structured,
                "blocked": row.blocked,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
