import base64
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from storeops.api import create_app
from storeops.config import Settings

SECRET = "shopify-test-app-shared-secret-very-long"
OPERATOR = "storeops-very-long-operator-key-for-tests"
SHOP = "demo-store.myshopify.com"
AUTH = {"X-Operator-Key": OPERATOR}


@pytest.fixture
def context(tmp_path):
    settings = Settings(database=tmp_path / "store.sqlite", operator_key=OPERATOR,
                        shopify_secret=SECRET, shop_domain=SHOP, low_stock_threshold=5,
                        high_value_cents=100000)
    client = TestClient(create_app(settings))
    return client


def time_at(minutes=0):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def order_payload(*, id=101, total="100.50", financial="paid", fulfillment=None, updated=None, cancelled=False):
    return {
        "id": id, "name": "#1001", "updated_at": updated or time_at(),
        "total_price": total, "currency": "USD", "financial_status": financial,
        "fulfillment_status": fulfillment,
        "cancelled_at": "2026-11-14T00:00:00Z" if cancelled else None,
        "line_items": [{"sku": "SHIRT-RED-M", "quantity": 2, "price": "50.25"}],
        "email": "customer@example.org",  # must not persist
    }


def signed(client, topic, payload, *, webhook_id=None, secret=SECRET, shop=SHOP, tamper=False):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()
    if tamper:
        raw += b" "
    return client.post("/webhooks/shopify", content=raw, headers={
        "X-Shopify-Hmac-Sha256": signature,
        "X-Shopify-Shop-Domain": shop,
        "X-Shopify-Topic": topic,
        "X-Shopify-Webhook-Id": webhook_id or str(uuid4()),
        "X-Shopify-Event-Id": str(uuid4()),
        "Content-Type": "application/json",
    })
