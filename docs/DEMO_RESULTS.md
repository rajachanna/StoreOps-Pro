# StoreOps Pro — Local Verification Report

Verification run: 2026-11-14 (local offline environment)

| Check | Result | Scope |
| --- | --- | --- |
| Python tests (`python -m pytest -q`) | **47 passed** | Logic, operator auth, webhook HMAC, order projections, inventory, return reviews |
| Synthetic scenario (`python scripts/demo.py`) | **PASS** | 3 orders, duplicate webhook, 3 stock snapshots, return-review states |
| Python package (`pip wheel --no-build-isolation --no-deps .`) | **PASS** | Successfully built `storeops_pro-0.1.0-py3-none-any.whl` |
| Packaged dashboard HTML | **PASS** | Verified `storeops/static/index.html` in wheel archive |
| Chromium isolated dashboard render | **PASS** | Browser-rendered local HTML with injected synthetic example records; no connected backend needed for the screenshot |
| Shopify account/live provider tests | **NOT EXECUTED** | Needs merchant-approved test store and app secret |
| Real refunds/fulfillment/stock writes | **NOT IMPLEMENTED** | Intentionally excluded |

## Synthetic scenario observed values

- `orders`: **3**
- `exceptions`: **2** (high-value and unpaid)
- `stock_items`: **3**
- `low_stock`: **2**
- `returns_pending`: **1**
- `webhook_deliveries`: **4** after replaying one duplicate delivery
- `alerts`: **4**

This report is a local verification record, **not a GitHub Actions result**. The included CI workflow must be run and inspected after uploading to GitHub. No external API performance, customer outcomes or deployment reliability are claimed.
