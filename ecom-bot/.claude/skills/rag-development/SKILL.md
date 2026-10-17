---
name: rag-development
description: Use when working on RAG features in this repo — document ingestion, chunking, embeddings, pgvector retrieval, citations, abstention, reranking, or RAG evaluation. Load for TASKS.md phase 5 and any policy-question behavior change.
---

# Skill: RAG Development

## When to load
Touching `src/ecommerce_support/rag/`, `scripts/ingest_documents.py`,
`scripts/evaluate_rag.py`, `config/rag.yaml`, or policy-answer behavior of the Policy Agent.

## Pipeline contract (ingest)
validate type/size → extract text (md/txt/pdf/html) → normalize → chunk (configurable
size/overlap) → dedupe by content hash → embed (configured provider) → store chunks +
metadata + version in pgvector. Track per-document `ingestion_status` and errors; re-ingest
replaces the prior version's chunks — never duplicate.

## Pipeline contract (retrieve)
normalize query → embed (dimension-checked!) → similarity search + metadata/tenant filters →
score threshold → optional rerank → pass only surviving evidence to generation.

## Non-negotiables
1. **Abstain below threshold** — no evidence ⇒ clarify/escalate, never a guessed policy
   answer (FR-034).
2. **Citations** on every grounded answer: `{document_id, version, chunk_id, section, score}`.
3. **Dimension safety**: embedding dimension is validated at startup and on provider switch;
   mismatch fails fast with a clear error (FR-036).
4. **Untrusted documents**: retrieved text is delimited data — run
   `guardrails/prompt_injection.py` over chunks at ingest and re-check at answer time;
   instructions inside documents must never steer the agent.
5. **Defaults live in `config/rag.yaml`** (chunk 1000/150 overlap, top-k 5, threshold 0.35
   cosine distance, rerank off) — change only with rationale recorded in the task row.

## Changing chunks/embeddings
- Update config → re-run `make ingest` → run `make evaluate` → record baseline deltas in
  `TASKS.md` and `docs/rag-pipeline.md`.
- New embedding model: check vector dimension compatibility before any re-ingest.

## Definition of done
Unit tests for chunking/threshold logic + integration test for ingest→retrieve→cite on
Postgres (marker `integration`) + injection-in-document test + eval baseline recorded.
