"""Orders: creation from the cart, shipping rates, payment checks, status workflow."""
from __future__ import annotations

from dataclasses import dataclass

from . import cart as cart_mod
from .db import DB, now

STATUSES = ("new", "paid", "packed", "shipped", "delivered", "cancelled")

# what an admin may switch an order to from each status ("paid" is set only by a real payment)
ADMIN_NEXT: dict[str, tuple[str, ...]] = {
    "new": ("cancelled",),
    "paid": ("packed", "cancelled"),
    "packed": ("shipped", "cancelled"),
    "shipped": ("delivered",),
    "delivered": (),
    "cancelled": (),
}

EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "GR", "HU", "IE", "IT", "LV", "LT",
      "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}


class OrderError(Exception):
    """code: empty_cart | not_found | not_yours | order_changed | stock_changed | no_shipping | bad_transition"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ShippingRate:
    id: str
    cents: int


def shipping_rates(country: str | None, subtotal_cents: int, free_de_from: int = 8000) -> list[ShippingRate]:
    cc = (country or "").upper()
    if not cc:
        return []
    if cc == "DE":
        std = 0 if subtotal_cents >= free_de_from else 490
        return [ShippingRate("de_std", std), ShippingRate("de_express", 990)]
    if cc in EU:
        return [ShippingRate("eu_std", 990)]
    return [ShippingRate("world", 1990)]


def shipping_cost(option_id: str | None, country: str | None, subtotal_cents: int,
                  free_de_from: int = 8000) -> int | None:
    for rate in shipping_rates(country, subtotal_cents, free_de_from):
        if rate.id == option_id:
            return rate.cents
    return None


def payload_for(order_id: int) -> str:
    return f"order:{order_id}"


def parse_payload(payload: str) -> int | None:
    kind, _, raw = (payload or "").partition(":")
    return int(raw) if kind == "order" and raw.isdigit() else None


def _event(db: DB, order_id: int, status: str, actor: str) -> None:
    db.conn.execute("INSERT INTO order_events(order_id,status,actor,at) VALUES (?,?,?,?)",
                    (order_id, status, actor, now()))


def create_order(db: DB, user_id: int, lang: str, currency: str = "EUR") -> int:
    """Snapshot the cart into a new unpaid order. Older unpaid orders of the user are cancelled,
    so a stale invoice can't be paid later."""
    view = cart_mod.get_cart(db, user_id, lang)
    if view.empty:
        raise OrderError("empty_cart")
    for line in view.lines:
        if line.qty > db.product(line.product_id)["stock"]:
            raise OrderError("stock_changed")
    ts = now()
    with db.conn:
        for old in db.all("SELECT id FROM orders WHERE user_id=? AND status='new'", user_id):
            db.conn.execute("UPDATE orders SET status='cancelled', updated_at=? WHERE id=?", (ts, old["id"]))
            _event(db, old["id"], "cancelled", "system:superseded")
        cur = db.conn.execute(
            "INSERT INTO orders(user_id,status,lang,currency,subtotal_cents,total_cents,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, "new", lang, currency, view.subtotal_cents, view.subtotal_cents, ts, ts))
        order_id = cur.lastrowid
        db.conn.executemany(
            "INSERT INTO order_items(order_id,product_id,name,size,qty,price_cents) VALUES (?,?,?,?,?,?)",
            [(order_id, ln.product_id, ln.name, ln.size, ln.qty, ln.price_cents) for ln in view.lines])
        _event(db, order_id, "new", f"user:{user_id}")
    return order_id


def get_order(db: DB, order_id: int) -> dict | None:
    row = db.one("SELECT * FROM orders WHERE id=?", order_id)
    if row is None:
        return None
    order = dict(row)
    order["items"] = [dict(r) for r in db.all("SELECT * FROM order_items WHERE order_id=?", order_id)]
    return order


def _check_open(db: DB, order_id: int | None, user_id: int, currency: str) -> dict:
    order = get_order(db, order_id) if order_id else None
    if order is None:
        raise OrderError("not_found")
    if order["user_id"] != user_id:
        raise OrderError("not_yours")
    if order["status"] != "new" or order["currency"] != currency:
        raise OrderError("order_changed")
    return order


def validate_shipping(db: DB, order_id: int | None, user_id: int, currency: str,
                      country: str | None, free_de_from: int = 8000) -> list[ShippingRate]:
    order = _check_open(db, order_id, user_id, currency)
    rates = shipping_rates(country, order["subtotal_cents"], free_de_from)
    if not rates:
        raise OrderError("no_shipping")
    return rates


def validate_pre_checkout(db: DB, order_id: int | None, user_id: int, currency: str, total_cents: int,
                          shipping_option: str | None, country: str | None, free_de_from: int = 8000) -> int:
    """Last check before Telegram charges the card. Returns the shipping cost."""
    order = _check_open(db, order_id, user_id, currency)
    for item in order["items"]:
        product = db.product(item["product_id"])
        if product is None or not product["active"] or product["stock"] < item["qty"]:
            raise OrderError("stock_changed")
    ship = shipping_cost(shipping_option, country, order["subtotal_cents"], free_de_from)
    if ship is None:
        raise OrderError("no_shipping")
    if total_cents != order["subtotal_cents"] + ship:
        raise OrderError("order_changed")
    return ship


def mark_paid(db: DB, order_id: int, charge_id: str, provider_charge_id: str, total_cents: int,
              shipping_option: str | None = None, info: dict | None = None) -> bool:
    """Record a successful payment. Idempotent: a re-delivered payment returns False."""
    info = info or {}
    if db.one("SELECT 1 FROM orders WHERE charge_id=?", charge_id):
        return False
    order = get_order(db, order_id)
    if order is None or order["status"] != "new":
        return False
    ts = now()
    with db.conn:
        for item in order["items"]:
            db.conn.execute("UPDATE products SET stock=MAX(stock-?,0) WHERE id=?",
                            (item["qty"], item["product_id"]))
        db.conn.execute(
            "UPDATE orders SET status='paid', charge_id=?, provider_charge_id=?, total_cents=?, "
            "shipping_cents=?, shipping_option=?, customer_name=?, phone=?, email=?, country=?, address=?, "
            "paid_at=?, updated_at=? WHERE id=?",
            (charge_id, provider_charge_id, total_cents, total_cents - order["subtotal_cents"],
             shipping_option, info.get("name"), info.get("phone"), info.get("email"),
             info.get("country"), info.get("address"), ts, ts, order_id))
        db.conn.execute("DELETE FROM cart_items WHERE user_id=?", (order["user_id"],))
        _event(db, order_id, "paid", "telegram")
    return True


def set_status(db: DB, order_id: int, status: str, actor: str) -> dict:
    order = get_order(db, order_id)
    if order is None:
        raise OrderError("not_found")
    if status not in ADMIN_NEXT.get(order["status"], ()):
        raise OrderError("bad_transition")
    with db.conn:
        if status == "cancelled" and order["status"] in ("paid", "packed"):
            for item in order["items"]:  # return reserved stock
                db.conn.execute("UPDATE products SET stock=stock+? WHERE id=?", (item["qty"], item["product_id"]))
        db.conn.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, now(), order_id))
        _event(db, order_id, status, actor)
    return get_order(db, order_id)


def list_orders(db: DB, status: str | None = None, limit: int = 10) -> list[dict]:
    if status:
        rows = db.all("SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ?", status, limit)
    else:
        rows = db.all("SELECT * FROM orders WHERE status!='new' ORDER BY id DESC LIMIT ?", limit)
    return [dict(r) for r in rows]


def user_orders(db: DB, user_id: int, limit: int = 5) -> list[dict]:
    rows = db.all("SELECT * FROM orders WHERE user_id=? AND status!='cancelled' OR "
                  "(user_id=? AND status='cancelled' AND paid_at IS NOT NULL) ORDER BY id DESC LIMIT ?",
                  user_id, user_id, limit)
    return [dict(r) for r in rows]


def stats(db: DB) -> dict:
    counts = {s: 0 for s in STATUSES}
    for r in db.all("SELECT status, COUNT(*) AS n FROM orders GROUP BY status"):
        counts[r["status"]] = r["n"]
    revenue = db.one("SELECT COALESCE(SUM(total_cents),0) AS s FROM orders WHERE paid_at IS NOT NULL "
                     "AND status!='cancelled'")["s"]
    customers = db.one("SELECT COUNT(*) AS n FROM users")["n"]
    return {"counts": counts, "revenue_cents": revenue, "customers": customers}
