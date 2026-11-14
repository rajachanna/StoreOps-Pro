from datetime import datetime,timezone,timedelta
from fastapi.testclient import TestClient
from storeops.api import create_app, valid_shopify_hmac
from storeops.config import Settings
from .conftest import AUTH, SECRET, SHOP, order_payload, signed, time_at


def test_health(context):
    assert context.get("/health").json()["status"]=="ready"


def test_dashboard(context):
    page=context.get("/")
    assert page.status_code==200
    assert "StoreOps" in page.text


def test_operator_requires_key(context):
    for url in ["/api/overview","/api/orders","/api/stock","/api/returns","/api/alerts","/api/audit"]:
        assert context.get(url).status_code==401
        assert context.get(url,headers={"X-Operator-Key":"wrong"}).status_code==401


def test_default_operator_secrets_fail_closed(tmp_path):
    c=TestClient(create_app(Settings(database=tmp_path/"x.sqlite")))
    assert c.get("/api/overview",headers={"X-Operator-Key":""}).status_code==401
    assert c.post("/webhooks/shopify").status_code==503


def test_signed_order_applies(context):
    r=signed(context,"orders/create",order_payload())
    assert r.status_code==200,r.text
    orders=context.get("/api/orders",headers=AUTH).json()["orders"]
    assert len(orders)==1
    assert orders[0]["total_cents"]==10050
    assert orders[0]["exception"]=="none"
    assert "email" not in orders[0]


def test_duplicate_delivery_idempotent(context):
    payload=order_payload()
    first=signed(context,"orders/create",payload,webhook_id="delivery-001")
    second=signed(context,"orders/create",payload,webhook_id="delivery-001")
    assert first.status_code==200 and second.status_code==200
    assert second.json()["duplicate"] is True
    assert context.get("/api/overview",headers=AUTH).json()["metrics"]["webhook_deliveries"]==1


def test_invalid_signature_rejected(context):
    r=signed(context,"orders/create",order_payload(),secret="a-different-long-secret-for-tests")
    assert r.status_code==403
    assert context.get("/api/orders",headers=AUTH).json()["orders"]==[]


def test_modified_body_rejected(context):
    assert signed(context,"orders/create",order_payload(),tamper=True).status_code==403


def test_wrong_shop_rejected(context):
    assert signed(context,"orders/create",order_payload(),shop="evil-store.myshopify.com").status_code==403


def test_unsupported_topic_rejected(context):
    assert signed(context,"customers/create",order_payload()).status_code==422


def test_broken_payload_never_acknowledged(context):
    r=signed(context,"orders/create",{"id":101,"updated_at":"today","total_price":"10"})
    assert r.status_code==422
    assert context.get("/api/overview",headers=AUTH).json()["metrics"]["webhook_deliveries"]==0


def test_event_timestamp_staleness(context):
    fresh=time_at(1)
    stale=time_at(-5)
    signed(context,"orders/create",order_payload(total="100.00",updated=fresh))
    r=signed(context,"orders/updated",order_payload(total="1.00",updated=stale))
    assert r.json()["applied"] is False
    assert context.get("/api/orders",headers=AUTH).json()["orders"][0]["total_cents"]==10000


def test_newer_event_updates_existing(context):
    signed(context,"orders/create",order_payload(total="100.00",updated=time_at(-3)))
    signed(context,"orders/updated",order_payload(total="200.00",updated=time_at(-2)))
    assert context.get("/api/orders",headers=AUTH).json()["orders"][0]["total_cents"]==20000


def test_order_payment_exception(context):
    signed(context,"orders/create",order_payload(financial="pending"))
    alerts=context.get("/api/alerts",headers=AUTH).json()["alerts"]
    assert len(alerts)==1
    assert alerts[0]["category"]=="payment_review"


def test_high_value_review(context):
    signed(context,"orders/create",order_payload(total="1000.00"))
    alerts=context.get("/api/alerts",headers=AUTH).json()["alerts"]
    assert alerts[0]["category"]=="high_value_review"


def test_product_low_stock(context):
    doc={"id":123,"updated_at":time_at(),"variants":[{"sku":"SKU-RED","inventory_quantity":3}]}
    r=signed(context,"products/update",doc)
    assert r.status_code==200
    assert context.get("/api/overview",headers=AUTH).json()["metrics"]["low_stock"]==1


def test_manual_inventory_set_is_audited(context):
    r=context.post("/api/stock",headers=AUTH,json={"sku":"SKU-RED","quantity":0})
    assert r.status_code==200
    assert "Does not change inventory on Shopify" in r.json()["note"]
    assert context.get("/api/audit",headers=AUTH).json()["events"][0]["event"]=="stock_set"


def test_bad_sku_is_rejected(context):
    assert context.post("/api/stock",headers=AUTH,json={"sku":"<script>","quantity":1}).status_code==422


def test_product_without_inventory_count_is_not_invented(context):
    doc={"id":123,"updated_at":time_at(),"variants":[{"sku":"SKU-RED"}]}
    assert signed(context,"products/update",doc).json()["applied"] is False
    assert context.get("/api/stock",headers=AUTH).json()["inventory"]==[]


def test_return_workflow(context):
    signed(context,"orders/create",order_payload(id=223))
    created=context.post("/api/returns",headers=AUTH,json={"order_id":"223","reason":"Customer reported damaged item"})
    assert created.status_code==200,created.text
    case_id=created.json()["id"]
    assert created.json()["status"]=="pending"
    assert context.get("/api/overview",headers=AUTH).json()["metrics"]["returns_pending"]==1
    reviewed=context.post(f"/api/returns/{case_id}/review",headers=AUTH,json={"decision":"approved","note":"Damage evidence reviewed"})
    assert reviewed.status_code==200
    assert reviewed.json()["status"]=="approved"
    assert context.get("/api/overview",headers=AUTH).json()["metrics"]["returns_pending"]==0
    assert context.post(f"/api/returns/{case_id}/review",headers=AUTH,json={"decision":"rejected","note":"Second decision"}).status_code==409
    assert context.get("/api/audit",headers=AUTH).json()["events"][0]["event"]=="return_reviewed"


def test_return_does_not_process_shopify_refund(context):
    signed(context,"orders/create",order_payload(id=223))
    created=context.post("/api/returns",headers=AUTH,json={"order_id":"223","reason":"Customer reported damaged item"}).json()
    approved=context.post(f"/api/returns/{created['id']}/review",headers=AUTH,json={"decision":"approved","note":"Refund needs separate execution"}).json()
    assert "refund_id" not in approved
    assert approved["reviewer_note"]=="Refund needs separate execution"


def test_return_unknown_order(context):
    assert context.post("/api/returns",headers=AUTH,json={"order_id":"9999","reason":"Missing item in delivery"}).status_code==404


def test_return_duplicate(context):
    signed(context,"orders/create",order_payload(id=223))
    body={"order_id":"223","reason":"Customer reported damaged item"}
    assert context.post("/api/returns",headers=AUTH,json=body).status_code==200
    assert context.post("/api/returns",headers=AUTH,json=body).status_code==409


def test_missing_hmac(context):
    assert context.post("/webhooks/shopify",json=order_payload()).status_code==403


def test_bad_base64(context):
    assert valid_shopify_hmac(SECRET,b"x","NOT!!base64") is False


def test_oversized_payload(context):
    r=context.post("/webhooks/shopify",content=b"x"*(262144+1))
    assert r.status_code==413
