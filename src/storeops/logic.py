"""Validation and deterministic retail operations logic."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone
import re

SUPPORTED_TOPICS = frozenset({"orders/create", "orders/updated", "products/update"})
SKU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,79}$")


class EventError(ValueError):
    pass


def parse_time(value):
    if not isinstance(value, str) or len(value) > 64:
        raise EventError("Expected event updated_at ISO-8601 timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventError("Invalid event timestamp") from exc
    if dt.tzinfo is None:
        raise EventError("Event timestamp must include timezone")
    from datetime import timedelta
    if dt.year < 2000 or dt > datetime.now(timezone.utc) + timedelta(days=365 * 3):
        raise EventError("Event timestamp out of range")
    return dt.astimezone(timezone.utc).isoformat()


def money_cents(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal("100000000"):
            raise EventError("Invalid amount")
        cents = number * 100
        if cents != cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP):
            raise EventError("Amount has more than two decimals")
        return int(cents)
    except (InvalidOperation, TypeError, ValueError) as exc:
        if isinstance(exc, EventError):
            raise
        raise EventError("Invalid decimal amount") from exc


def parse_order(doc):
    if not isinstance(doc, dict):
        raise EventError("Order payload must be an object")
    identifier = str(doc.get("id", ""))
    if not identifier.isdecimal() or len(identifier) > 25:
        raise EventError("Shopify order id must be numeric")
    currency = doc.get("currency", "USD")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise EventError("Currency must be a 3-letter ISO code")
    updated_at = parse_time(doc.get("updated_at"))
    items = doc.get("line_items", [])
    if not isinstance(items, list) or len(items) > 500:
        raise EventError("Invalid line items")
    parsed_items = []
    for item in items:
        if not isinstance(item, dict):
            raise EventError("Invalid line item")
        sku = str(item.get("sku") or "").strip()
        if not sku or not SKU_RE.fullmatch(sku):
            continue  # valid real-world Shopify line items can lack SKU
        qty = item.get("quantity")
        if type(qty) is not int or qty < 0 or qty > 100000:
            raise EventError("Invalid line item quantity")
        parsed_items.append({"sku": sku, "quantity": qty})
    financial = str(doc.get("financial_status") or "unknown").lower()[:40]
    fulfillment = str(doc.get("fulfillment_status") or "unfulfilled").lower()[:40]
    if doc.get("cancelled_at"):
        fulfillment = "cancelled"
    return {
        "external_id": identifier,
        "order_number": str(doc.get("name") or f"#{identifier}")[:60],
        "updated_at": updated_at,
        "total_cents": money_cents(doc.get("total_price")),
        "currency": currency,
        "financial_status": financial,
        "fulfillment_status": fulfillment,
        "line_items": parsed_items,
    }


def parse_product(doc):
    if not isinstance(doc, dict):
        raise EventError("Product payload must be object")
    updated_at = parse_time(doc.get("updated_at"))
    variants = doc.get("variants", [])
    if not isinstance(variants, list) or len(variants) > 500:
        raise EventError("Invalid product variants")
    cleaned = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        sku = str(variant.get("sku") or "").strip()
        if not SKU_RE.fullmatch(sku):
            continue
        # Shopify products/update may not include inventory_quantity in every API version.
        # Never invent a stock count if that field is absent.
        qty = variant.get("inventory_quantity")
        if type(qty) is not int or qty < 0 or qty > 10**8:
            continue
        cleaned.append({"sku": sku, "quantity": qty, "updated_at": updated_at})
    return cleaned


def order_exception(financial_status, fulfillment_status, total_cents, high_value_cents):
    if fulfillment_status == "cancelled":
        return "cancelled"
    if financial_status not in {"paid", "partially_refunded", "refunded"}:
        return "payment_review"
    if total_cents >= high_value_cents and fulfillment_status not in {"fulfilled", "cancelled"}:
        return "high_value_review"
    return "none"
