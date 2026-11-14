# Roadmap

## v0.1 (this project): verified local foundation

- FastAPI operator API and dashboard
- Signed Shopify-style webhook parsing with mocked provider deliveries
- Per-store delivery deduplication, stale event rejection and SQLite persistence
- Payment/high-value exceptions, stock alerts, local manual stock updates
- Human-reviewed returns and auditable decision history
- Automated tests, synthetic end-to-end demo and build packaging

## Milestone 2 — merchant sandbox verification

- Shopify custom app installation on a developer test store and subscribed topics
- Live event signing/headers/API-version verification
- Initial GraphQL Admin API bulk historical sync and periodical reconciliation
- Explicit stock source/location handling and store subscription reconciliation
- Retry queue and dead-letter handling, rate limits and webhook response latency

## Milestone 3 — integrations and reliability

- Fulfillment partner or 3PL/WMS API connector with sandbox first
- Location-aware availability, purchase-order drafting, supplier notification approvals
- Idempotent outbound writes (still human gated)
- Returns authorization against actual Shopify returns/refunds (explicit merchant approval)
- Multi-store accounts, staff RBAC and complete customer privacy controls

## Milestone 4 — production readiness

- Load tests, tenant isolation, backup/restore, audit policy, observability
- Real fault injection, rate limits, OAuth, secret rotation and CI security scans
- Human user acceptance and documented provider test evidence

No automated real-world Shopify writes, live store operations or revenue uplift are claimed for v0.1.
