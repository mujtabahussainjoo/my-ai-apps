"""Shared schema primitives."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
Price = Annotated[float, Field(gt=0)]
Probability = Annotated[float, Field(ge=0, le=1)]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(BaseModel):
    """Strict base model: unknown fields are rejected, never silently ignored.

    Strictness matters here because these models are the boundary between the
    deterministic engine, the LLM, and execution. A typo'd field that is quietly
    dropped is how a risk limit stops applying.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
        validate_assignment=True,
        arbitrary_types_allowed=False,
    )
