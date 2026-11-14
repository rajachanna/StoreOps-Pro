# StoreOps Pro — Engineering Case Study

**Author:** Raja Channa | NextGen Tech Solutions

## Challenge

Online retail operations require visibility into exceptional orders, product inventory snapshots and return requests. Replayed and out-of-order webhook events can corrupt naive integrations, while a false "refund issued" indicator can be costly.

## Solution scope

Implemented a focused **local prototype**: Shopify-compatible signed HTTPS receiver, SQLite order/stock projections, rule-based exceptions, manually managed returns and an operator dashboard. Demonstration uses only synthetic payloads and a fictional test store.

## Key engineering decisions

| Risk | Mitigation | Limitation |
| --- | --- | --- |
| Fake inbound webhook | HMAC-SHA256 over original bytes, constant-time compare, allowlisted shop | No actual Shopify account verified |
| Duplicate deliveries | Atomic unique `(shop, webhook_id)` | Missed events still require reconciliation |
| Out-of-order events | UTC-normalized `updated_at` precedence | Provider payload version differences need integration testing |
| Invalid amounts | Decimal to integer cents, reject negative/non-finite/over-precise | Real multicurrency commerce requires further rules |
| False inventory count | Only accept explicit `inventory_quantity`, never decrement from orders | No source-of-truth location-level stock sync |
| Unsafe returns | Pending → reviewed state machine with audit; no external API write | No automatic refund/return label functionality |
| Leaked PII | Ignore Shopify email/address/customer fields | Order values/notes remain sensitive business data |
| Dashboard exposure | Require secret for all operator APIs | SSO/RBAC not implemented; local use recommended |

## Repeatable synthetic demo

1. Import three fictional orders using signed request headers.
2. Replay a delivery ID and verify it is deduplicated.
3. Import three stock snapshots and detect two low-stock SKUs.
4. Observe high-value and unpaid exceptions.
5. Create two review cases, approve one and leave the second pending.
6. Inspect dashboard metrics and audit trail; verify that no real Shopify refund took place.

Run `python scripts/demo.py` and `python -m pytest -q` after installing the project. CI runs the same verification on GitHub.

## Value proposition and deliverables

This portfolio demonstrates backend/data engineering, transaction integrity, third-party webhook security and practical operator UX. A paid engagement would begin with authorization, store characteristics, fulfillment rules, real sandbox API testing and documented acceptance criteria.

**Not evidenced:** production deployment, live store uptime, Shopify API reconciliation, automatic fulfillment, real refunds, sales gains or AI decision-making.

**Developer:** https://github.com/rajachanna | https://nextgentechdev.com
