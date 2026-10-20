"""Policy document and chunk persistence, including pgvector embeddings.

DATA-001 ``policy_documents``/``document_chunks``; versioning and content-hash dedupe per
DATA-006. The embedding dimension is fixed at the schema level; embedding providers must
match it (validated in the ingestion path, TASK-018).
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ecommerce_support.core.constants import EMBEDDING_DIMENSIONS
from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import CreatedAtMixin, TimestampMixin, enum_column_type
from ecommerce_support.schemas.enums import DocumentStatus

__all__ = ["EMBEDDING_DIMENSIONS", "DocumentChunk", "PolicyDocument"]


class PolicyDocument(Base, TimestampMixin):
    """A versioned policy/FAQ document (one row per version)."""

    __tablename__ = "policy_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "version", name="uq_policy_document_version"),
        Index("ix_policy_documents_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", server_default="default", index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        enum_column_type(DocumentStatus, "document_status"),
        nullable=False,
        default=DocumentStatus.PENDING,
        index=True,
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentChunk(Base, CreatedAtMixin):
    """A chunk of a document version with an optional embedding vector."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("policy_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
