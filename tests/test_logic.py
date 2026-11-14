from datetime import datetime, timezone
import pytest
from storeops.logic import EventError, money_cents, parse_time, parse_order, parse_product, order_exception
from storeops.config import Settings
from .conftest import order_payload

@pytest.mark.parametrize("text,cents", [("0",0),("1.99",199),("1000.00",100000),("0.01",1),(42,4200)])
def test_money_valid(text,cents):
    assert money_cents(text)==cents

@pytest.mark.parametrize("text",["-1","1.111","NaN","Infinity",None,"hello","1000000000"])
def test_money_invalid(text):
    with pytest.raises(EventError): money_cents(text)

def test_parse_timestamp_requires_offset():
    with pytest.raises(EventError): parse_time("2026-11-14T12:00:00")

def test_parse_timestamp_normalizes_offset():
    assert parse_time("2026-11-14T12:00:00+05:00") == "2026-11-14T07:00:00+00:00"

def test_order_personal_data_excluded():
    order=parse_order(order_payload())
    assert "email" not in order
    assert "name" not in order
    assert order["total_cents"]==10050
    assert order["line_items"] == [{"sku":"SHIRT-RED-M","quantity":2}]

def test_no_sku_does_not_break_order():
    doc=order_payload(); doc["line_items"]=[{"sku":"","quantity":2}]
    assert parse_order(doc)["line_items"]==[]

def test_product_missing_stock_count_not_invented():
    products=parse_product({"updated_at":order_payload()["updated_at"], "variants":[{"sku":"SHIRT-RED-M"}]})
    assert products == []

def test_product_valid_stock_count():
    products=parse_product({"updated_at":order_payload()["updated_at"], "variants":[{"sku":"SHIRT-RED-M","inventory_quantity":3}]})
    assert products[0]["quantity"]==3

def test_cancelled_override():
    assert parse_order(order_payload(cancelled=True))["fulfillment_status"]=="cancelled"

def test_exception_rules():
    assert order_exception("pending","unfulfilled",123,1000)=="payment_review"
    assert order_exception("paid","unfulfilled",1000,1000)=="high_value_review"
    assert order_exception("paid","fulfilled",1000,1000)=="none"
    assert order_exception("pending","cancelled",1000,1000)=="cancelled"

def test_bad_settings():
    with pytest.raises(ValueError): Settings(shop_domain="attacker.com").validate()
    with pytest.raises(ValueError): Settings(high_value_cents=-10).validate()
