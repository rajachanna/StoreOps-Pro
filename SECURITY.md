# Security, privacy and data limitations

StoreOps Pro v0.1 is an offline-first engineering prototype. **Not a production Shopify app or payment system.**

- All operator API endpoints need an independent, high-entropy `STOREOPS_OPERATOR_KEY` (24+ characters). Unset and placeholder keys fail closed.
- Shopify incoming webhook endpoints are disabled unless both the app secret and the allowed `myshopify.com` shop domain are configured.
- HMAC is calculated over the **raw HTTP body**, decoded from Base64, and compared using constant-time equality. `X-Shopify-Hmac-Sha256` and `X-Shopify-Webhook-Id` are required; only an allowed store domain is accepted.
- No calls to the Shopify Admin API, fulfillment services, refund endpoints, or payout APIs are implemented. Manual return approval is a local review label only.
- Event replay/idempotency uses the delivery ID. Real production integration must independently handle webhooks that never arrive, timestamp anomalies, secret rotation, API version changes and outages.
- The system deliberately does not save email/phone/customer address from incoming order JSON. It does preserve order IDs, numbers, SKU/quantity, prices and payment/fulfillment status; these may still be business-sensitive.
- SQLite uses parameterized SQL, per-request connections, a write transaction and a unique index for delivery IDs. It is not intended for multi-region production scale.
- The server's dashboard HTML is publicly fetchable; the actual records require the operator key. In a real deployment, **also gate the dashboard itself** behind authentication, enforce TLS, rate-limit all routes and use real staff RBAC/session handling.
- Do not store tokens or production customer data in public repositories, CI logs, issue attachments or screenshots.
- Use explicit merchant authorization and privacy policies for data collection. Configure backup, retention, deletion, auditing and incident response before accepting real traffic.
- Container demo binds host port to 127.0.0.1 only; exposing it on the public Internet without HTTPS and firewall controls is unsafe.
- Sensitive PII is not ingested into the order projection, but manual return reasons and review notes are persisted and should not include private contact details.
- No AI model is currently connected and no actual sales improvement or conversion outcome has been measured.

Report vulnerabilities privately through the company website: https://nextgentechdev.com
