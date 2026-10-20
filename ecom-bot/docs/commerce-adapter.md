# Commerce Adapter

The commerce backend sits behind one interface, `CommerceAdapter`
(`src/ecommerce_support/integrations/commerce.py`). Agents and tools depend only on that
interface, never on a specific backend (FR-041 / INT-003).

## Interface

| Method | Returns | Purpose |
| --- | --- | --- |
| `get_order(order_id)` | `Order \| None` | Full order (items, totals, status, shipment) |
| `list_orders(customer_id, limit, offset)` | `(list[OrderSummary], total)` | A customer's own orders |
| `track_shipment(order_id)` | `Shipment \| None` | Carrier / tracking / status for an order |
| `return_eligibility(order_id)` | `ReturnEligibility \| None` | Return decision + window |
| `search_products(query)` | `(list[ProductSummary], total)` | Catalog search |
| `get_product(product_id)` | `Product \| None` | Full product detail |
| `stock_info(product_id)` | `StockInfo \| None` | Stock availability |

All methods are `async` and return Pydantic schemas from `schemas/` — never ORM objects.

## Implementations

- **`SqlCommerceAdapter`** (`integrations/sql_commerce.py`) — **mock/fixture-only** for v1. Reads
  the seeded demo `orders` / `products` tables via the repositories. This is *not* a production
  source of truth (DATA-004); return-eligibility is computed here from order state using
  `core.constants.RETURN_WINDOW_DAYS`.
- **`InMemoryCommerceAdapter`** (`integrations/memory_commerce.py`) — dependency-free mock for unit
  tests and framework-free agent runs.

## Adding a real backend (e.g. Magento / Adobe Commerce)

This is a documented extension point; no Magento code ships in v1.

1. Create `integrations/magento.py` with a class implementing every `CommerceAdapter` method.
   Map Magento REST responses onto the existing schemas — do not add backend-specific fields to
   shared contracts.
2. Translate HTTP/API errors to `IntegrationError` / `CommerceError` (`core/exceptions.py`); do
   not leak credentials or raw payloads into messages.
3. Select the adapter where adapters are built (dependency wiring), driven by configuration.
   No agent or tool code changes.
4. Convert Magento's return-window rules into the `ReturnEligibility` result; keep
   `core.constants.RETURN_WINDOW_DAYS` only as the fixture default.
5. Add contract tests that run the same suite against both the fixture and the new adapter.

## Ownership

Ownership is enforced in the **tools** (`tools/order.py`), not the adapter: a tool compares
`order.customer_id` to the authenticated `ToolContext.user_id` and reports anything else as
not-found (SEC-002 / FR-040). The adapter returns raw data and must not be used to bypass that
check.
