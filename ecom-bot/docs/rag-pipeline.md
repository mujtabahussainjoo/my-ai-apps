# RAG Pipeline

Policy/FAQ retrieval-augmented generation (`src/ecommerce_support/rag/`). The pipeline is:
**load → normalize → chunk → embed → store (pgvector) → retrieve → rerank → grounded
generation → cite / abstain**. Commerce data and ticketing are explicitly out of scope here
(those live in `integrations/` and worker tools).

## Status by stage

| Stage | Module | Task | Status |
| --- | --- | --- | --- |
| Load + validate + normalize | `rag/loaders.py`, `rag/normalization.py` | TASK-016 | Implemented |
| Chunking, versioning, ingestion tracking | `rag/chunking.py`, `rag/hashing.py`, `rag/ingestion.py` | TASK-017 | Implemented |
| Embeddings + pgvector persistence | `rag/embeddings/`, `rag/store.py` | TASK-018 | Implemented |
| Retrieval + metadata filters + rerank | `rag/retrieval.py`, `rag/rerank.py` | TASK-019 | Implemented |
| Grounded generation, citations, abstention | `rag/generation.py`, `guardrails/prompt_injection.py` | TASK-020 | Implemented |
| Eval dataset + baseline metrics | `evaluation/`, `scripts/evaluate_rag.py`, `evals/` | TASK-021 | Implemented |
| Policy worker (retrieval tool + grounding) | `tools/policy.py`, `agents/workers/policy.py` | TASK-025 | Implemented |

## Ingestion: loading and normalization (TASK-016)

Contract: **validate type/size → extract text → normalize**.

- **Supported formats**: Markdown, plain text, PDF, HTML. Type is resolved from an explicit
  media type first (`text/plain; charset=...` parameters are ignored), then the filename
  extension (`.md/.markdown`, `.txt/.text`, `.pdf`, `.html/.htm`). An optional allowlist
  (`allowed_types`) can further restrict ingestion.
- **Size validation happens before parsing** so oversized uploads are rejected cheaply.
  `load_document(..., max_bytes=...)` defaults to 10 MB; production callers pass
  `settings.limits.max_document_bytes`. Failures are loud and typed:
  `DocumentTooLargeError`, `UnsupportedDocumentTypeError`, `IngestionError` (empty/unparseable).
- **Extraction**: PDF via `pypdf` (encrypted PDFs are rejected); HTML via BeautifulSoup with
  `script/style/noscript/template/head/iframe/object` removed; Markdown reduced to prose
  (headings, emphasis, links, list/quote markers, and code-fence markers stripped, code content
  kept); text/Markdown decoded as UTF-8 with `errors="replace"` (never fatal).
- **Normalization** (`normalize_text`) is deterministic and idempotent: Unicode NFKC folding,
  CRLF/CR → LF, exotic Unicode spaces → ASCII space, control characters removed (NUL/C0/C1),
  runs of spaces/tabs collapsed, per-line trailing whitespace stripped, 3+ blank lines collapsed
  to one, ends trimmed.
- **Security**: extracted text is *data*, never instructions. Control-character stripping is a
  baseline; the retrieved-text injection check and delimiting are added with chunking/retrieval
  and `guardrails/prompt_injection.py` (TASK-017/023).

`load_document` returns a `LoadedDocument` (`source`, `filename`, `media_type`, `document_type`,
`byte_size`, normalized `text`) consumed by the chunker.

## Chunking, versioning, ingestion tracking (TASK-017)

Chunking is deterministic and framework-free (`rag/chunking.py`):

- `split_sections(text)` splits on blank-line blocks and promotes a short standalone capitalized
  line (≤80 chars, ≤12 words, not ending in `. , ; :`) to a `section_title`. This is a documented
  heuristic tuned for policy/FAQ documents whose headings are single short lines; a heading with
  no body is kept as its own section so nothing is dropped.
- `chunk_text(text, chunk_size=…, chunk_overlap=…)` windows each section to at most `chunk_size`
  characters, trimming back to a paragraph → sentence → newline boundary when one lies in the
  second half of the window, and carries `chunk_overlap` characters of context across the seam.
  It assigns sequential `index`, estimates `token_count` (~4 chars/token), and **de-dupes identical
  chunks by SHA-256 content hash** so repeated boilerplate is stored once per document.
- Invalid windows fail loudly (`ValueError`): `chunk_size > 0`, `0 ≤ chunk_overlap < chunk_size`.

`rag/hashing.py::content_hash` is the stable dedupe key (content only, no timestamps).

`rag/ingestion.py` is **transaction-scoped — it never commits**; the caller owns the transaction
(`db.session.session_scope`) so a failed ingest can be rolled back and its failure recorded
separately:

- `ingest_document(session, loaded, …)` returns `IngestionResult{document, deduplicated,
  chunk_count}`. When the normalized content is unchanged and the latest version is `indexed`, it
  is a no-op (`deduplicated=True`, same document id/version). Otherwise it creates version N+1 and
  marks the previously indexed version `superseded`. Chunks are persisted with **null vectors**
  until embeddings land in TASK-018. `chunk_size`/`chunk_overlap` default to `RagConfig`.
- `mark_ingestion_failed(session, source, error, …)` persists a `failed` newest-version row with a
  truncated `error_message` (stored on `policy_documents.error_message`, migration
  `dd1be3f02adf`) in a *fresh* transaction. Callers roll back the failed ingest first so the
  abandoned `processing` row does not persist.

Retrieved/`indexed` documents are versioned by `(tenant_id, source, version)`; embeddings are added
in TASK-018 (chunks are stored with a null vector until then).

## Chunking and retrieval defaults

Defaults live in `config/rag.yaml` (overridable via `RAG__*` env vars):

| Setting | Default | Rationale |
| --- | --- | --- |
| `chunk_size` | 1000 chars | ≈150–200 words keeps a full policy clause intact |
| `chunk_overlap` | 150 chars | preserves sentence context across boundaries |
| `top_k` | 5 | balances recall against prompt size |
| `distance_threshold` | 0.35 (cosine) | below-threshold evidence ⇒ abstain rather than guess |
| `rerank_enabled` | false | optional cross-encoder rerank, off by default |

Embedding dimension is fixed at the schema level (`1536`) and must be validated at startup and
on provider switch — a mismatch fails fast (FR-036). Citations carry
`{document_id, version, chunk_id, section_title, score}` (FR-033).

## Embeddings and pgvector persistence (TASK-018)

Embeddings are provider-neutral (`rag/embeddings/`): callers depend on the `EmbeddingProvider` ABC,
and `create_embedding_provider()` selects the implementation from `LLMConfig.embedding_provider`
(`mock | openai | ollama | huggingface`). `LLMConfig.embedding_dimensions` defaults to `1536` and
the DB column is `vector(1536)`.

- **`mock`** (default, tests/offline): deterministic unit-norm vectors derived from a SHA-256
  expansion of the text — no network, no credentials, reproducible ordering.
- **`openai`**: `AsyncOpenAI.embeddings.create`; requires `LLM__OPENAI_API_KEY`. Errors normalize
  to `EmbeddingError`.
- **`ollama`**: `POST /api/embed` via `httpx` (injectable; offline-testable).
- **`huggingface`**: not supported by this build (no local model runtime) — fails loudly with
  `ConfigurationError`.

**Dimension safety (FR-036)**: `EmbeddingProvider.embed` validates the batch shape and every vector
length; `PgVectorStore.replace_document_chunks` re-checks before writing; and
`check_embedding_dimensions` runs as a readiness check (`/ready`) so a misconfigured provider is
caught at startup. A mismatch raises `EmbeddingDimensionError` (non-retryable) rather than storing
a wrong-length vector.

`ingest_document(..., embedder=…)` embeds the chunk batch and stores the vectors through
`PgVectorStore` (a thin, dimension-guarding wrapper over `DocumentRepository.replace_chunks`). When
`embedder` is omitted, chunks are stored with null vectors. Retrieval over these vectors is
TASK-019.

## Retrieval, metadata filters, rerank (TASK-019)

Pipeline (`rag/retrieval.py`): **normalize query → embed (dimension-checked) → vector search
(tenant + filters) → distance threshold → optional rerank → bounded scores**. Only evidence that
survives the threshold is returned; if nothing survives, `RetrievalResult.abstained` is `True` so
the caller clarifies/escalates instead of guessing (FR-034).

- **Search** (`DocumentRepository.search_chunks`, exposed via `PgVectorStore.search`) joins chunks
  to their document and searches only `indexed` versions of the caller's `tenant_id`. The query
  vector's length is checked against `vector(1536)` (FR-036).
- **Distance metrics**: `cosine` (default), `l2`, `ip` — selected by `rag.distance_metric`;
  an unknown metric raises `ConfigurationError`. Results are ordered by ascending distance.
- **Metadata filters** (`RetrievalQuery.filters`): `document_id`, `version` (integer),
  `section_title`, `source`, `title`. An unrecognized key raises `ValidationError` rather than
  being silently ignored.
- **Score** is a bounded `[0, 1]` similarity derived from the raw distance
  (`similarity_from_distance`): cosine `1 − d`, l2 `1/(1 + d)`, ip `(−d + 1)/2`.
- **Threshold**: `apply_threshold` keeps hits with `distance ≤ rag.distance_threshold`; a `None`
  per-query threshold disables filtering.
- **Rerank (optional, off by default)**: when `rag.rerank_enabled`, the retriever widens the
  candidate set to `max(top_k, rerank_top_n)` and reorders via `rag/rerank.py`. The bundled
  `LexicalReranker` scores by query-token coverage (deterministic, offline); swap it for a neural
  cross-encoder by implementing the `Reranker` protocol — no retrieval changes required.

`Retriever.retrieve(query, tenant_id=…)` accepts a plain string (uses config defaults) or a
`RetrievalQuery` (per-call `top_k`/`distance_threshold`/`filters` overrides). Build it with
`Retriever.from_session(session, embedder, RagConfig())` / `create_retriever(...)`. Grounded
generation, citations, and abstention messaging are TASK-020.

## Grounded generation, citations, abstention (TASK-020)

`rag/generation.py::GroundedGenerator.answer(query, retrieval) -> GroundedAnswer` turns a
`RetrievalResult` into a cited answer or an explicit abstention:

- **Trust screen**: each retrieved chunk is scanned by `guardrails/prompt_injection.py`
  (`assess_prompt_injection`/`is_prompt_injection`, weighted heuristic patterns for
  instruction-override, jailbreak, prompt/secret exfiltration, role spoofing). Chunks scoring at
  or above `guardrails.max_prompt_injection_score` (default `0.7`) are dropped. If *all* evidence
  is dropped the generator abstains with `reason="untrusted_evidence"` and never calls the LLM.
- **Delimited evidence**: surviving hits are numbered and wrapped in `<policy>…</policy>`; the
  system prompt states this is untrusted reference text, not instructions. Retrieved instructions
  therefore cannot steer the answer (FR-032).
- **Generation**: one `complete` call (`temperature=0`) over the evidence block; the LLM is told
  to answer only from the block and to cite bracketed numbers.
- **Citations**: `to_citation` maps each used hit to a `SourceCitation`
  (`document_id`, `chunk_id`, `document_title`, `section_title`, `version`, `score`) — FR-033.
- **Abstention** (FR-034): `abstained=True` with `reason` in
  `no_evidence` | `untrusted_evidence` | `empty_generation`, returning `ABSTAIN_MESSAGE`.

Wire it with `create_grounded_generator(client, rag, guardrails)` (reads `top_k` as the chunk cap
and `guardrails.max_prompt_injection_score`). The generator is framework-free (no LangChain) and
uses the provider-independent `LLMClient`; the policy worker (TASK-022+) consumes it.

## Evaluation (TASK-021)

- **Dataset**: `evals/rag_dataset.yaml` is a versioned set of cases (`id`, `question`,
  `expected_documents`, optional `expected_quote`, `should_abstain`). The corpus lives in
  `evals/corpus/*.md`.
- **Harness** (`evaluation/rag.py`): `load_eval_dataset` parses YAML/JSON and fails loudly on
  malformed input; `RagEvaluator(retriever, generator, top_k, distance_threshold, tenant_id)`
  runs every case and returns a `RagEvalReport`. Metrics: `recall` (expected documents present),
  `groundedness` (cited answer or correct abstention), `abstention_accuracy`, `pass_rate`.
  The harness is pipeline-agnostic — inject the real retriever/generator or test doubles.
- **Runner**: `uv run python -m scripts.evaluate_rag [--dataset ...] [--corpus ...] [--tenant ...]
  [--keep]`. It ingests the corpus into a throwaway tenant, runs the set, prints
  `render_report`, and cleans up (`DocumentRepository.delete_by_tenant`). Set
  `--min-pass-rate` to gate CI.
- **Baseline (checked in, offline)**: with the mock embedder + lexical rerank and the threshold
  disabled it reports `recall=1.000, groundedness=0.857, abstention=0.857, pass_rate=0.857` on the
  `v1` set — the single miss is the `gift-wrapping` abstention case, which offline cannot detect
  (mock distances are not semantic). Configure a real embedding provider
  (`LLM__EMBEDDING_PROVIDER`) for meaningful abstention numbers. Seed corpus is demo data, not
  production policy.
- **Integration test**: `tests/integration/test_rag_eval_pipeline.py` ingests the corpus, asserts
  the answerable cases retrieve their document with citations, and that `delete_by_tenant` cleans
  up.