"""Secured operator API and signed Shopify-style HTTPS webhook receiver."""
import base64
import binascii
import hashlib
import hmac
import json
import re
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .config import Settings
from .logic import SUPPORTED_TOPICS, SKU_RE, EventError, parse_order, parse_product
from .store import Store

MAX_WEBHOOK_BYTES = 256 * 1024
WEBHOOK_ID = re.compile(r"^[A-Za-z0-9_.:-]{5,100}$")


class StockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=0, le=100000000)


class ReturnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=25, pattern=r"^[0-9]+$")
    reason: str = Field(min_length=8, max_length=160)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern=r"^(approved|rejected)$")
    note: str = Field(min_length=4, max_length=240)


def valid_shopify_hmac(secret: str, body: bytes, supplied: str) -> bool:
    """Compare decoded HMAC digest using constant-time compare_digest."""
    try:
        provided = base64.b64decode(supplied, validate=True)
    except (ValueError, binascii.Error):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(provided, expected)


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    settings.validate()
    store = Store(settings)
    app = FastAPI(
        title="StoreOps Pro — Ecommerce Operations Automation",
        version=__version__,
        description="Local operations prototype. Signed Shopify webhooks are supported; live store connection is unverified.",
    )

    def operator_only(x_operator_key: str | None = Header(default=None)):
        if (not settings.operator_enabled or not x_operator_key or
                not hmac.compare_digest(settings.operator_key, x_operator_key)):
            raise HTTPException(401, "Invalid operator key")

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/health")
    def health():
        return {
            "status": "ready", "version": __version__,
            "mode": "SHOPIFY_WEBHOOKS_CONFIGURED_NOT_PROVIDER_VERIFIED" if settings.webhooks_enabled else "OFFLINE_DEMO",
        }

    @app.post("/webhooks/shopify")
    async def webhook(request: Request):
        # Always fail closed if no trusted store and app secret are configured.
        if not settings.webhooks_enabled:
            raise HTTPException(503, "Shopify webhook receiver not configured")
        # Read the raw body once, never serialize parsed JSON for verification.
        raw = await request.body()
        if len(raw) > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "Webhook too large")
        if not valid_shopify_hmac(
            settings.shopify_secret, raw, request.headers.get("x-shopify-hmac-sha256", "")
        ):
            raise HTTPException(403, "Invalid Shopify HMAC")
        domain = request.headers.get("x-shopify-shop-domain", "")
        if domain != settings.shop_domain:
            raise HTTPException(403, "Unexpected store domain")
        topic = request.headers.get("x-shopify-topic", "")
        if topic not in SUPPORTED_TOPICS:
            raise HTTPException(422, "Unsupported Shopify webhook topic")
        webhook_id = request.headers.get("x-shopify-webhook-id", "")
        if not WEBHOOK_ID.fullmatch(webhook_id):
            raise HTTPException(422, "Webhook delivery id missing or malformed")
        event_id = request.headers.get("x-shopify-event-id", "")[:100]
        try:
            doc = json.loads(raw)
            if topic in {"orders/create", "orders/updated"}:
                order = parse_order(doc)
                result = store.apply_webhook(
                    shop=domain, webhook_id=webhook_id, event_id=event_id,
                    topic=topic, order=order,
                )
            else:
                variants = parse_product(doc)
                result = store.apply_webhook(
                    shop=domain, webhook_id=webhook_id, event_id=event_id,
                    topic=topic, variants=variants,
                )
        except (EventError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(422, "Invalid webhook payload: " + str(exc)[:120]) from exc
        return {"accepted": True, **result}

    @app.get("/api/overview", dependencies=[Depends(operator_only)])
    def overview():
        return {"shop": settings.shop_domain or "demo-store.myshopify.com", "metrics": store.metrics(settings.shop_domain or "demo-store.myshopify.com")}

    def active_shop():
        return settings.shop_domain or "demo-store.myshopify.com"

    @app.get("/api/orders", dependencies=[Depends(operator_only)])
    def orders():
        return {"orders": store.list_orders(active_shop())}

    @app.get("/api/stock", dependencies=[Depends(operator_only)])
    def inventory():
        return {"inventory": store.list_stock(active_shop())}

    @app.post("/api/stock", dependencies=[Depends(operator_only)])
    def adjust_stock(item: StockInput):
        if not SKU_RE.fullmatch(item.sku):
            raise HTTPException(422, "Invalid SKU characters")
        store.upsert_stock(active_shop(), item.sku, item.quantity)
        return {"sku": item.sku, "quantity": item.quantity, "source": "operator_manual", "note": "Does not change inventory on Shopify"}

    @app.get("/api/alerts", dependencies=[Depends(operator_only)])
    def alerts():
        return {"alerts": store.alerts(active_shop())}

    @app.post("/api/returns", dependencies=[Depends(operator_only)])
    def create_return(req: ReturnInput):
        try:
            return store.new_return(active_shop(), req.order_id, req.reason.strip())
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/returns", dependencies=[Depends(operator_only)])
    def returns():
        return {"returns": store.list_returns(active_shop())}

    @app.post("/api/returns/{ticket_id}/review", dependencies=[Depends(operator_only)])
    def review(ticket_id: str, req: ReviewInput):
        if not re.fullmatch(r"[0-9a-f]{32}", ticket_id):
            raise HTTPException(404, "Unknown return case")
        try:
            return store.review_return(active_shop(), ticket_id, req.decision, req.note)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/audit", dependencies=[Depends(operator_only)])
    def audit():
        return {"events": store.list_audit()}

    return app


app = create_app()
