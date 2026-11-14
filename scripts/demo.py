"""One-command synthetic StoreOps demo. No real Shopify store or credentials.

Usage: python scripts/demo.py
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import base64
import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from storeops.api import create_app
from storeops.config import Settings

TEST_KEY = "demo-only-in-memory-key-2026-storeops"
TEST_SECRET = "synthetic-shopify-secret-not-a-real-app"
SHOP = "demo-store.myshopify.com"


def send_signed(client: TestClient, topic: str, payload: dict, *, delivery_id: str | None = None):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = base64.b64encode(hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).digest()).decode()
    return client.post("/webhooks/shopify", content=body, headers={
        "X-Shopify-Hmac-Sha256": signature,
        "X-Shopify-Webhook-Id": delivery_id or str(uuid4()),
        "X-Shopify-Event-Id": str(uuid4()),
        "X-Shopify-Shop-Domain": SHOP,
        "X-Shopify-Topic": topic,
        "Content-Type": "application/json",
    })


def main():
    with TemporaryDirectory(prefix="storeops-synthetic-") as directory:
        settings = Settings(
            database=Path(directory) / "demo.sqlite", operator_key=TEST_KEY,
            shopify_secret=TEST_SECRET, shop_domain=SHOP,
            low_stock_threshold=5, high_value_cents=100000,
        )
        client = TestClient(create_app(settings))
        auth = {"X-Operator-Key": TEST_KEY}
        ts = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        print("StoreOps Pro — SYNTHETIC OFFLINE DEMO; NO LIVE SHOPIFY CONNECTION")
        orders = [
            (101, "#SO-1001", "1500.00", "paid", "unfulfilled"),
            (102, "#SO-1002", "79.99", "pending", "unfulfilled"),
            (103, "#SO-1003", "32.50", "paid", "fulfilled"),
        ]
        for id, name, amount, payment, fulfillment in orders:
            payload = {
                "id": id, "name": name, "updated_at": ts,
                "total_price": amount, "currency": "USD",
                "financial_status": payment, "fulfillment_status": fulfillment,
                "line_items": [{"sku": "TSHIRT-001", "quantity": 1}],
                "email": "fictional-customer@example.invalid",
            }
            result = send_signed(client, "orders/create", payload, delivery_id=f"demo-order-{id}")
            assert result.status_code == 200, result.text
        print("✓ Three authenticated synthetic order deliveries")
        duplicate = send_signed(client, "orders/create", payload, delivery_id="demo-order-103")
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"]
        print("✓ Duplicate delivery acknowledged without reprocessing")
        stock = {
            "id": 501, "updated_at": ts,
            "variants": [
                {"sku": "TSHIRT-001", "inventory_quantity": 20},
                {"sku": "SHOES-BLK", "inventory_quantity": 2},
                {"sku": "MUG-002", "inventory_quantity": 0},
            ],
        }
        response = send_signed(client, "products/update", stock)
        assert response.status_code == 200
        print("✓ Three product SKU snapshots including two low-stock alerts")
        created = client.post("/api/returns", headers=auth, json={
            "order_id": "103", "reason": "Synthetic item arrived damaged",
        })
        assert created.status_code == 200, created.text
        reviewed = client.post(
            f"/api/returns/{created.json()['id']}/review", headers=auth,
            json={"decision": "approved", "note": "Approved for review; no external refund"},
        )
        assert reviewed.status_code == 200
        pending = client.post("/api/returns", headers=auth, json={
            "order_id": "102", "reason": "Customer requests sizing exchange",
        })
        assert pending.status_code == 200
        print("✓ Manual return review and separate pending case (no refund executed)")
        metrics = client.get("/api/overview", headers=auth).json()["metrics"]
        alerts = client.get("/api/alerts", headers=auth).json()["alerts"]
        assert metrics["orders"] == 3
        assert metrics["exceptions"] == 2
        assert metrics["low_stock"] == 2
        assert metrics["returns_pending"] == 1
        assert metrics["webhook_deliveries"] == 4
        assert len(alerts) == 4
        assert len(client.get("/api/audit", headers=auth).json()["events"]) == 3
        print("\nFINAL VERIFIABLE SYNTHETIC RESULT:")
        print(json.dumps({"metrics": metrics, "alert_categories": [a["category"] for a in alerts]}, indent=2))
        print("\nPASS — no external Shopify API calls, refunds, or live customers involved.")


if __name__ == "__main__":
    main()
