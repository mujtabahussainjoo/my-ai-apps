"""Chat, approval and activity routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexapilot.api.deps import ContainerDep, SessionDep
from nexapilot.core.container import Container
from nexapilot.db.models import TaskRun
from nexapilot.services.chat_service import ChatInput, ChatService

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequestSchema(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: str = Field(default="", max_length=64)
    workflow: str = Field(default="", max_length=32)
    timezone: str = Field(default="UTC", max_length=80)


class DecisionSchema(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=2000)


class CancelSchema(BaseModel):
    task_run_id: str = Field(default="", max_length=64)
    conversation_id: str = Field(default="", max_length=64)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _chat_service(request: Request) -> ChatService:
    container: Container = request.app.state.container
    return ChatService(container, request.app.state.registry, request.app.state.graph)


@router.post("/chat")
async def chat(
    payload: ChatRequestSchema,
    request: Request,
    container: Container = ContainerDep,
) -> StreamingResponse:
    """Stream a chat turn as Server-Sent Events."""
    service = _chat_service(request)
    session = container.session_factory()
    cancel_event = asyncio.Event()
    request.app.state.active_runs[payload.conversation_id or "new"] = cancel_event

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.run_chat(
                session,
                ChatInput(
                    message=payload.message,
                    conversation_id=payload.conversation_id,
                    workflow=payload.workflow,
                    timezone=payload.timezone,
                ),
                cancel_event=cancel_event,
            ):
                yield _sse(event)
        except asyncio.CancelledError:
            yield _sse({"type": "cancelled", "message": "The run was cancelled."})
            raise
        except Exception as exc:
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            session.close()
            request.app.state.active_runs.pop(payload.conversation_id or "new", None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/cancel")
async def cancel_chat(payload: CancelSchema, request: Request) -> dict[str, Any]:
    key = payload.conversation_id or payload.task_run_id or "new"
    cancel_event: asyncio.Event | None = request.app.state.active_runs.get(key)
    if cancel_event is None:
        return {"status": "no_active_run"}
    cancel_event.set()
    return {"status": "cancelling"}


@router.get("/conversations")
def list_conversations(request: Request, session: Session = SessionDep) -> list[dict[str, Any]]:
    service = ChatService(
        request.app.state.container, request.app.state.registry, request.app.state.graph
    )
    return service.list_conversations(session)


@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: str, request: Request, session: Session = SessionDep
) -> list[dict[str, Any]]:
    service = ChatService(
        request.app.state.container, request.app.state.registry, request.app.state.graph
    )
    return service.list_messages(session, conversation_id)


@router.get("/approvals")
def list_approvals(status: str = "", session: Session = SessionDep) -> list[dict[str, Any]]:
    from nexapilot.services import approvals as approval_service

    requests = approval_service.list_requests(session, status=status or None)
    return [
        {
            "id": item.id,
            "task_run_id": item.task_run_id,
            "action": item.action,
            "title": item.title,
            "description": item.description,
            "target": item.target,
            "provider": item.provider,
            "risk": item.risk,
            "cost": item.cost,
            "consequences": item.consequences,
            "status": item.status,
            "created_at": item.created_at.isoformat(),
            "decided_at": item.decided_at.isoformat() if item.decided_at else None,
            "payload": item.payload,
        }
        for item in requests
    ]


@router.post("/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: str, payload: DecisionSchema, session: Session = SessionDep
) -> dict[str, Any]:
    from nexapilot.services import approvals as approval_service

    try:
        request = approval_service.decide(
            session, approval_id, approved=payload.approved, note=payload.note
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return {"id": request.id, "status": request.status}


@router.post("/approvals/{approval_id}/resume")
async def resume_approval(
    approval_id: str, request: Request, container: Container = ContainerDep
) -> StreamingResponse:
    service = _chat_service(request)
    session = container.session_factory()

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.resume_approved_action(session, approval_id=approval_id):
                yield _sse(event)
        except Exception as exc:
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            session.close()

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@router.get("/activity")
def list_activity(session: Session = SessionDep, limit: int = 50) -> list[dict[str, Any]]:
    from sqlalchemy import select

    rows = list(
        session.scalars(select(TaskRun).order_by(TaskRun.created_at.desc()).limit(min(limit, 200)))
    )
    return [
        {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "workflow": row.workflow,
            "status": row.status,
            "provider": row.provider,
            "model": row.model,
            "steps": row.steps,
            "error": row.error,
            "started_at": row.started_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }
        for row in rows
    ]
