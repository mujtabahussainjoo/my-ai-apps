"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from nexapilot.core.container import Container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def get_session(request: Request) -> Iterator[Session]:
    container: Container = request.app.state.container
    session = container.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


ContainerDep = Depends(get_container)
SessionDep = Depends(get_session)


def get_tool_registry(request: Request) -> Any:
    return request.app.state.registry
