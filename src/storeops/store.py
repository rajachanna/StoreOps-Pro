"""Transactional SQLite projections, case reviews and audit records.

All Shopify webhooks are treated as notifications, not a financial ledger.
No Shopify API writes or outgoing emails are implemented.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import sqlite3

from .config import Settings
from .logic import order_exception


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.validate()
        Path(settings.database).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    webhook_id TEXT NOT NULL,
                    shop TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    event_id TEXT,
                    applied INTEGER NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY (shop, webhook_id));
                CREATE TABLE IF NOT EXISTS orders (
                    shop TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    order_number TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    total_cents INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    financial_status TEXT NOT NULL,
                    fulfillment_status TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    PRIMARY KEY (shop, external_id));
                CREATE TABLE IF NOT EXISTS inventory (
                    shop TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    PRIMARY KEY(shop, sku));
                CREATE TABLE IF NOT EXISTS return_cases (
                    id TEXT PRIMARY KEY,
                    shop TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reviewer_note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    UNIQUE(shop,order_id,reason));
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(str(self.settings.database), timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=15000")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
        finally:
            con.close()

    def apply_webhook(self, *, shop, webhook_id, topic, event_id, order=None, variants=None):
        """Apply verified, prevalidated webhook exactly once per delivery id.

        A later version wins, avoiding overwrites from out-of-order deliveries.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            seen = db.execute(
                "SELECT applied FROM deliveries WHERE shop=? AND webhook_id=?",
                (shop, webhook_id),
            ).fetchone()
            if seen is not None:
                db.execute("COMMIT")
                return {"duplicate": True, "applied": bool(seen["applied"])}
            applied = False
            if order is not None:
                existing = db.execute(
                    "SELECT updated_at FROM orders WHERE shop=? AND external_id=?",
                    (shop, order["external_id"]),
                ).fetchone()
                if existing is None or existing["updated_at"] < order["updated_at"]:
                    db.execute(
                        """INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(shop,external_id) DO UPDATE SET
                          order_number=excluded.order_number,
                          updated_at=excluded.updated_at,
                          total_cents=excluded.total_cents,
                          currency=excluded.currency,
                          financial_status=excluded.financial_status,
                          fulfillment_status=excluded.fulfillment_status,
                          items_json=excluded.items_json""",
                        (shop, order["external_id"], order["order_number"], order["updated_at"],
                         order["total_cents"], order["currency"], order["financial_status"],
                         order["fulfillment_status"], json.dumps(order["line_items"])),
                    )
                    applied = True
            elif variants is not None:
                for variant in variants:
                    existing = db.execute(
                        "SELECT updated_at FROM inventory WHERE shop=? AND sku=?",
                        (shop, variant["sku"]),
                    ).fetchone()
                    if existing is None or existing["updated_at"] < variant["updated_at"]:
                        db.execute(
                            """INSERT INTO inventory VALUES(?,?,?,?,?)
                            ON CONFLICT(shop,sku) DO UPDATE SET
                              quantity=excluded.quantity,updated_at=excluded.updated_at,source=excluded.source""",
                            (shop, variant["sku"], variant["quantity"], variant["updated_at"],
                             "product_snapshot"),
                        )
                        applied = True
            db.execute(
                "INSERT INTO deliveries VALUES(?,?,?,?,?,?)",
                (webhook_id, shop, topic, event_id, 1 if applied else 0, utc_now()),
            )
            db.execute("COMMIT")
            return {"duplicate": False, "applied": applied}

    def upsert_stock(self, shop, sku, quantity):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO inventory VALUES(?,?,?,?,?)
                ON CONFLICT(shop,sku) DO UPDATE SET quantity=excluded.quantity,
                  updated_at=excluded.updated_at,source=excluded.source""",
                (shop, sku, quantity, utc_now(), "operator_manual"),
            )
            db.execute("INSERT INTO audit(event,object_id,details,created_at) VALUES(?,?,?,?)",
                       ("stock_set", sku, f"Manual stock quantity set to {quantity}", utc_now()))
            db.execute("COMMIT")

    def list_orders(self, shop, limit=200):
        with self.connect() as db:
            records = [dict(r) for r in db.execute(
                "SELECT * FROM orders WHERE shop=? ORDER BY updated_at DESC LIMIT ?", (shop, limit)
            )]
        for item in records:
            item["items"] = json.loads(item.pop("items_json"))
            item["exception"] = order_exception(
                item["financial_status"], item["fulfillment_status"], item["total_cents"],
                self.settings.high_value_cents,
            )
        return records

    def list_stock(self, shop):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM inventory WHERE shop=? ORDER BY sku LIMIT 500", (shop,)
            )]

    def get_order(self, shop, order_id):
        with self.connect() as db:
            return db.execute(
                "SELECT external_id FROM orders WHERE shop=? AND external_id=?",
                (shop, order_id),
            ).fetchone() is not None

    def new_return(self, shop, order_id, reason):
        if not self.get_order(shop, order_id):
            raise KeyError("Unknown order")
        ticket_id = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("INSERT INTO return_cases VALUES(?,?,?,?,?,?,?,?)",
                           (ticket_id, shop, order_id, reason, "pending", "", utc_now(), None))
            except sqlite3.IntegrityError as exc:
                db.execute("ROLLBACK")
                raise ValueError("Matching return review case already exists") from exc
            db.execute("INSERT INTO audit(event,object_id,details,created_at) VALUES(?,?,?,?)",
                       ("return_created", ticket_id, "Pending manual review", utc_now()))
            db.execute("COMMIT")
        return self.get_return(shop, ticket_id)

    def get_return(self, shop, ticket_id):
        with self.connect() as db:
            r = db.execute("SELECT * FROM return_cases WHERE shop=? AND id=?",
                           (shop, ticket_id)).fetchone()
            return dict(r) if r else None

    def review_return(self, shop, ticket_id, decision, note):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM return_cases WHERE shop=? AND id=?",
                             (shop, ticket_id)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                raise KeyError("Return case not found")
            if row["status"] != "pending":
                db.execute("ROLLBACK")
                raise ValueError("Return case has already been reviewed")
            db.execute("UPDATE return_cases SET status=?,reviewer_note=?,reviewed_at=? WHERE id=?",
                       (decision, note, utc_now(), ticket_id))
            db.execute("INSERT INTO audit(event,object_id,details,created_at) VALUES(?,?,?,?)",
                       ("return_reviewed", ticket_id, decision + ": " + note, utc_now()))
            db.execute("COMMIT")
        return self.get_return(shop, ticket_id)

    def list_returns(self, shop):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM return_cases WHERE shop=? ORDER BY created_at DESC LIMIT 200",
                (shop,),
            )]

    def list_audit(self, limit=100):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
            )]

    def metrics(self, shop):
        orders = self.list_orders(shop)
        stock = self.list_stock(shop)
        returns = self.list_returns(shop)
        with self.connect() as db:
            deliveries = db.execute("SELECT COUNT(*) FROM deliveries WHERE shop=?",(shop,)).fetchone()[0]
        exceptions = [x for x in orders if x["exception"] != "none"]
        low = [x for x in stock if x["quantity"] <= self.settings.low_stock_threshold]
        return {
            "orders": len(orders), "exceptions": len(exceptions),
            "stock_items": len(stock), "low_stock": len(low),
            "returns_pending": sum(x["status"] == "pending" for x in returns),
            "webhook_deliveries": deliveries,
            "note": "Counts reflect up to the latest 200 locally synced orders and 500 stock records. No Shopify store reconciliation.",
        }

    def alerts(self, shop):
        orders = self.list_orders(shop)
        inventory = self.list_stock(shop)
        alerts = []
        for item in orders:
            if item["exception"] != "none":
                alerts.append({"category": item["exception"], "object": item["order_number"],
                               "detail": f"Order {item['external_id']} requires operator review"})
        for item in inventory:
            if item["quantity"] <= self.settings.low_stock_threshold:
                alerts.append({"category": "low_stock", "object": item["sku"],
                               "detail": f"Available snapshot: {item['quantity']} units ({item['source']})"})
        return alerts[:200]
