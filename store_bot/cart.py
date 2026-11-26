"""Cart logic: pure functions over the DB, no Telegram here."""
from __future__ import annotations

from dataclasses import dataclass

from .db import DB, loc, sizes_of


class CartError(Exception):
    """code is an i18n key suffix: out_of_stock | unavailable | bad_size"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class CartLine:
    product_id: int
    name: str
    size: str
    qty: int
    price_cents: int

    @property
    def total_cents(self) -> int:
        return self.qty * self.price_cents

    @property
    def label(self) -> str:
        return f"{self.name} ({self.size})" if self.size else self.name


@dataclass
class CartView:
    lines: list[CartLine]

    @property
    def subtotal_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    @property
    def count(self) -> int:
        return sum(line.qty for line in self.lines)

    @property
    def empty(self) -> bool:
        return not self.lines


def _in_cart(db: DB, user_id: int, product_id: int) -> int:
    row = db.one("SELECT COALESCE(SUM(qty),0) AS n FROM cart_items WHERE user_id=? AND product_id=?",
                 user_id, product_id)
    return row["n"]


def add_item(db: DB, user_id: int, product_id: int, size: str = "", qty: int = 1) -> int:
    """Add qty of a product (in a size). Returns the new quantity of that line."""
    if qty < 1:
        raise ValueError("qty must be positive")
    product = db.product(product_id)
    if product is None or not product["active"]:
        raise CartError("unavailable")
    sizes = sizes_of(product)
    if (sizes and size not in sizes) or (not sizes and size):
        raise CartError("bad_size")
    # stock is per product: all sizes together may not exceed it
    if _in_cart(db, user_id, product_id) + qty > product["stock"]:
        raise CartError("out_of_stock")
    with db.conn:
        db.conn.execute(
            "INSERT INTO cart_items(user_id,product_id,size,qty) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id,product_id,size) DO UPDATE SET qty=qty+excluded.qty",
            (user_id, product_id, size, qty))
    return db.one("SELECT qty FROM cart_items WHERE user_id=? AND product_id=? AND size=?",
                  user_id, product_id, size)["qty"]


def remove_item(db: DB, user_id: int, product_id: int, size: str = "", qty: int = 1) -> int:
    """Decrease a line; deletes it at zero. Returns the remaining quantity."""
    row = db.one("SELECT qty FROM cart_items WHERE user_id=? AND product_id=? AND size=?",
                 user_id, product_id, size)
    if row is None:
        return 0
    left = row["qty"] - qty
    with db.conn:
        if left <= 0:
            db.conn.execute("DELETE FROM cart_items WHERE user_id=? AND product_id=? AND size=?",
                            (user_id, product_id, size))
        else:
            db.conn.execute("UPDATE cart_items SET qty=? WHERE user_id=? AND product_id=? AND size=?",
                            (left, user_id, product_id, size))
    return max(left, 0)


def clear(db: DB, user_id: int) -> None:
    with db.conn:
        db.conn.execute("DELETE FROM cart_items WHERE user_id=?", (user_id,))


def get_cart(db: DB, user_id: int, lang: str = "en") -> CartView:
    """Current cart with live prices. Lines whose product was hidden are dropped."""
    rows = db.all(
        "SELECT c.product_id, c.size, c.qty, p.* FROM cart_items c JOIN products p ON p.id=c.product_id "
        "WHERE c.user_id=? ORDER BY p.id, c.size", user_id)
    lines = [CartLine(r["product_id"], loc(r, "name", lang), r["size"], r["qty"], r["price_cents"])
             for r in rows if r["active"]]
    return CartView(lines)


def count(db: DB, user_id: int) -> int:
    return db.one("SELECT COALESCE(SUM(qty),0) AS n FROM cart_items WHERE user_id=?", user_id)["n"]
