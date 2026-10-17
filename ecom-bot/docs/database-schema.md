# Database Schema

PostgreSQL 16 + [pgvector](https://github.com/pgvector/pgvector) schema for the
e-commerce AI support assistant. Async access is via SQLAlchemy 2.x (`src/ecommerce_support/db`),
and every change ships as an Alembic migration.

- **Migrations**
  - `50f0c29c7ff2` — enables the `vector` extension (root revision).
  - `dec95a6bfcee` — initial schema: the 13 tables below (head).
- **Embedding dimension** — `1536` (`EMBEDDING_DIMENSIONS`), stored as `vector(1536)`.
- **Conventions** — `snake_case` tables/columns; string IDs `VARCHAR(64)` generated in the
  application (`core/ids.new_id`); timezone-aware `created_at`/`updated_at` with a Python
  default (`utcnow`) **and** a `now()` server default; enum columns are non-native
  `VARCHAR(32)` + named `CHECK` constraints (no PostgreSQL `ENUM` types); a deterministic
  naming convention (`ck_`, `fk_`, `pk_`, `uq_`, `ix_`) is applied in `db/base.py`.

Requirements mapping: `requirement.md` §7 (DATA-001…DATA-006).

## Tables

### `users`
Identity reference only — **no credentials or secrets** (SEC-001).

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `email` | `varchar(320)` | not null, unique |
| `display_name` | `varchar(200)` | null |
| `created_at` / `updated_at` | `timestamptz` | not null |

Indexes: `ix_users_email` (unique).

### `conversations`
Support conversations, optionally owned by a user (guests allowed). `tenant_id` provides
multi-store readiness (DATA-005).

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `user_id` | `varchar(64)` | FK → `users.id` `ON DELETE SET NULL`, null |
| `tenant_id` | `varchar(64)` | not null, default `default` |
| `status` | enum `conversation_status` | not null (FR-047 lifecycle values) |
| `resolution_outcome` | enum `resolution_outcome` | null |
| `created_at` / `updated_at` | `timestamptz` | not null |

Indexes: `ix_conversations_tenant_status` (`tenant_id`, `status`), `ix_conversations_status`,
`ix_conversations_tenant_id`, `ix_conversations_user_id`.
Checks: `ck_conversations_conversation_status`, `ck_conversations_resolution_outcome`.

### `messages`
Ordered messages within a conversation.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `conversation_id` | `varchar(64)` | FK → `conversations.id` `ON DELETE CASCADE` |
| `role` | enum `message_role` | not null |
| `content` | `text` | not null |
| `agent` | enum `agent_name` | null |
| `created_at` | `timestamptz` | not null |

Indexes: `ix_messages_conversation_created` (`conversation_id`, `created_at`),
`ix_messages_conversation_id`.
Checks: `ck_messages_message_role`, `ck_messages_agent_name`.

### `products`
Catalog products (mock fixtures in dev; commerce adapter is the production source — DATA-004).

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `sku` | `varchar(64)` | not null, unique |
| `name` | `varchar(200)` | not null |
| `description` | `text` | null |
| `category` | `varchar(100)` | not null |
| `price` | `numeric(12,2)` | not null |
| `currency` | `varchar(3)` | not null |
| `stock_status` | enum `stock_status` | not null |
| `stock_quantity` | `integer` | null |
| `attributes` | `json` | not null, default `{}` |
| `created_at` / `updated_at` | `timestamptz` | not null |

Indexes: `ix_products_sku` (unique), `ix_products_category`.
Checks: `ck_products_stock_status`.

### `orders`
Customer orders. Address/shipment are stored as `json` mirroring the adapter contracts.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `customer_id` | `varchar(64)` | FK → `users.id` `ON DELETE CASCADE` |
| `status` | enum `order_status` | not null |
| `currency` | `varchar(3)` | not null |
| `total` | `numeric(12,2)` | not null |
| `placed_at` | `timestamptz` | not null |
| `shipping_address` | `json` | null |
| `shipment` | `json` | null |
| `created_at` / `updated_at` | `timestamptz` | not null |

Indexes: `ix_orders_customer_placed` (`customer_id`, `placed_at`), `ix_orders_customer_id`,
`ix_orders_status`.
Checks: `ck_orders_order_status`.

### `order_items`
Line items; `product_id` uses `ON DELETE RESTRICT` to preserve order history.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `order_id` | `varchar(64)` | FK → `orders.id` `ON DELETE CASCADE` |
| `product_id` | `varchar(64)` | FK → `products.id` `ON DELETE RESTRICT` |
| `name` | `varchar(200)` | not null |
| `quantity` | `integer` | not null |
| `unit_price` / `line_total` | `numeric(12,2)` | not null |
| `created_at` | `timestamptz` | not null |

Indexes: `ix_order_items_order_id`, `ix_order_items_product_id`.

### `policy_documents`
Versioned policy/FAQ documents (DATA-006). Unique per `(tenant_id, source, version)`.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `tenant_id` | `varchar(64)` | not null, default `default` |
| `title` | `varchar(300)` | not null |
| `source` | `varchar(1000)` | not null |
| `version` | `integer` | not null |
| `content_hash` | `varchar(128)` | not null |
| `status` | enum `document_status` | not null |
| `chunk_count` | `integer` | not null |
| `created_at` / `updated_at` | `timestamptz` | not null |

Unique: `uq_policy_document_version` (`tenant_id`, `source`, `version`).
Indexes: `ix_policy_documents_tenant_status` (`tenant_id`, `status`), `ix_policy_documents_tenant_id`,
`ix_policy_documents_status`, `ix_policy_documents_source`.
Checks: `ck_policy_documents_document_status`.

### `document_chunks`
Chunks of a document version with their embeddings. Unique per `(document_id, chunk_index)`.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `document_id` | `varchar(64)` | FK → `policy_documents.id` `ON DELETE CASCADE` |
| `version` | `integer` | not null |
| `chunk_index` | `integer` | not null |
| `content` | `text` | not null |
| `content_hash` | `varchar(128)` | not null |
| `section_title` | `varchar(300)` | null |
| `token_count` | `integer` | null |
| `embedding` | `vector(1536)` | null |
| `created_at` | `timestamptz` | not null |

Unique: `uq_document_chunk_index` (`document_id`, `chunk_index`).
Indexes: `ix_document_chunks_document_id`; `ix_document_chunks_embedding_hnsw` —
HNSW index using `vector_cosine_ops` for approximate nearest-neighbour search (FR-031).

### `feedback`
Customer ratings (FR-052). `resolution_outcome` is a distinct enum constraint name from the
one on `conversations` so the two `CHECK` constraints can coexist.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `conversation_id` | `varchar(64)` | FK → `conversations.id` `ON DELETE CASCADE` |
| `rating` | `integer` | not null, `CHECK` 1–5 (`ck_feedback_rating_range`) |
| `comment` | `text` | null |
| `resolution_outcome` | enum `feedback_resolution_outcome` | null |
| `created_at` | `timestamptz` | not null |

Indexes: `ix_feedback_conversation`, `ix_feedback_outcome`, `ix_feedback_rating`.
Checks: `ck_feedback_rating_range`, `ck_feedback_feedback_resolution_outcome`.

### `support_tickets`
Escalation tickets with idempotent creation (FR-043/044). `idempotency_key` is unique.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `conversation_id` | `varchar(64)` | FK → `conversations.id` `ON DELETE CASCADE` |
| `tenant_id` | `varchar(64)` | not null, default `default` |
| `provider` | enum `ticket_provider` | not null |
| `status` | enum `ticket_status` | not null |
| `summary` | `varchar(255)` | not null |
| `priority` | enum `ticket_priority` | not null |
| `external_id` | `varchar(255)` | null |
| `url` | `varchar(1000)` | null |
| `idempotency_key` | `varchar(128)` | null, unique |
| `request_payload` | `json` | null (redacted before dispatch — FR-051) |
| `description` | `text` | null |
| `created_at` / `updated_at` | `timestamptz` | not null |

Indexes: `ix_support_tickets_conversation`, `ix_support_tickets_idempotency_key` (unique),
`ix_support_tickets_status`, `ix_support_tickets_tenant_id`.
Checks: `ck_support_tickets_ticket_provider`, `ck_support_tickets_ticket_status`,
`ck_support_tickets_ticket_priority`.

### `tool_executions`
Audit of tool invocations (redacted summaries only — SEC-010).

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `conversation_id` | `varchar(64)` | FK → `conversations.id` `ON DELETE SET NULL`, null |
| `message_id` | `varchar(64)` | FK → `messages.id` `ON DELETE SET NULL`, null |
| `tool_name` | `varchar(100)` | not null |
| `call_id` | `varchar(64)` | not null |
| `status` | enum `tool_call_status` | not null |
| `summary` | `text` | not null |
| `duration_ms` | `double precision` | null |
| `created_at` | `timestamptz` | not null |

Indexes: `ix_tool_executions_conversation`, `ix_tool_executions_tool_name`.
Checks: `ck_tool_executions_tool_call_status`.

### `audit_events`
Append-only audit log; `detail` must be redacted (SEC-010).

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `event_type` | `varchar(100)` | not null |
| `actor_id` | `varchar(64)` | null |
| `resource_type` | `varchar(100)` | null |
| `resource_id` | `varchar(64)` | null |
| `conversation_id` | `varchar(64)` | null |
| `detail` | `json` | not null, default `{}` |
| `created_at` | `timestamptz` | not null |

Indexes: `ix_audit_events_type_created` (`event_type`, `created_at`), `ix_audit_events_event_type`,
`ix_audit_events_conversation_id`.

### `eval_results`
RAG evaluation metric observations (FR-055).

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `varchar(64)` | PK |
| `dataset_version` | `varchar(64)` | not null |
| `case_id` | `varchar(64)` | not null |
| `metric` | `varchar(100)` | not null |
| `score` | `double precision` | not null |
| `detail` | `json` | not null, default `{}` |
| `created_at` | `timestamptz` | not null |

Indexes: `ix_eval_results_dataset_metric` (`dataset_version`, `metric`),
`ix_eval_results_dataset_version`.

## Repositories

`src/ecommerce_support/db/repositories/` holds one repository per aggregate. They translate
ORM rows to typed Pydantic schemas, **never** return ORM objects, and **never** commit — the
caller owns the transaction via `db.session.session_scope`. Relationships are loaded with
explicit `selectinload` (never implicit lazy loads) so they are safe under async I/O.

| Repository | Highlights |
| --- | --- |
| `UserRepository` | `upsert` (lowercases email), `get` |
| `ConversationRepository` | `create`, `get` (with messages), `get_summary`, `append_message`, `update_status`, `list_for_user` |
| `ProductRepository` | `get`, `get_by_sku`, `stock_info`, `search`, `list_products`, `upsert_many` |
| `OrderRepository` | `get`, `list_for_customer`, `upsert` (replaces items) |
| `DocumentRepository` | `create`, `get_by_source_version`, `list_documents`, `supersede`, `replace_chunks`, `list_chunks`, `delete_chunks` |
| `FeedbackRepository` | `create`, `get`, `list_by_conversation`, `count_by_rating`, `count_by_outcome` |
| `TicketRepository` | `create_idempotent`, `get_by_idempotency_key`, `update`, `list_by_conversation` |
| `AuditEventRepository` | `record`, `list_for_conversation` |
| `ToolExecutionRepository` | `record`, `list_for_conversation` |
| `EvalResultRepository` | `record_many`, `list_by_dataset` |

Repository tests live in `tests/integration/test_repositories.py` (marker `integration`,
auto-skipped when PostgreSQL is unreachable). Each test runs inside a transaction that is
rolled back.

## Commands

```bash
make db-up        # start PostgreSQL+pgvector (host port 5434)
make migrate      # apply migrations (alembic upgrade head)
make migrate-down # roll back the last migration
make test         # includes integration tests (skipped if DB is not reachable)
```
