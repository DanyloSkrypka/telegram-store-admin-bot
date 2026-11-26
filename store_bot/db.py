"""SQLite storage: schema, demo catalog seed, users and catalog queries.

Money is stored in integer cents. Product names/descriptions are stored per language.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .i18n import LANGS, detect_lang

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, first_name TEXT, username TEXT,
    lang TEXT NOT NULL DEFAULT 'en', created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL,
    title_en TEXT NOT NULL, title_de TEXT NOT NULL, title_ru TEXT NOT NULL, sort INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name_en TEXT NOT NULL, name_de TEXT NOT NULL, name_ru TEXT NOT NULL,
    desc_en TEXT DEFAULT '', desc_de TEXT DEFAULT '', desc_ru TEXT DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    sizes TEXT DEFAULT '',            -- comma separated, empty = one size
    photo_path TEXT, photo_file_id TEXT,
    active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cart_items (
    user_id INTEGER NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id),
    size TEXT NOT NULL DEFAULT '', qty INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (user_id, product_id, size)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new', lang TEXT NOT NULL DEFAULT 'en',
    currency TEXT NOT NULL, subtotal_cents INTEGER NOT NULL,
    shipping_cents INTEGER NOT NULL DEFAULT 0, shipping_option TEXT,
    total_cents INTEGER NOT NULL,
    customer_name TEXT, phone TEXT, email TEXT, country TEXT, address TEXT,
    charge_id TEXT UNIQUE, provider_charge_id TEXT,
    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, paid_at INTEGER
);
CREATE TABLE IF NOT EXISTS order_items (
    order_id INTEGER NOT NULL REFERENCES orders(id), product_id INTEGER NOT NULL,
    name TEXT NOT NULL, size TEXT NOT NULL DEFAULT '', qty INTEGER NOT NULL,
    price_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS order_events (
    order_id INTEGER NOT NULL, status TEXT NOT NULL, actor TEXT NOT NULL, at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
"""

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "products"

SEED_CATEGORIES = [
    ("tees", "T-shirts", "T-Shirts", "Футболки"),
    ("hoodies", "Hoodies", "Hoodies", "Худи"),
    ("accessories", "Accessories", "Accessoires", "Аксессуары"),
]

# slug, names (en, de, ru), descriptions (en, de, ru), price cents, stock, sizes, photo
SEED_PRODUCTS = [
    ("tees", ("Classic Logo Tee", "Classic Logo Tee", "Футболка Classic Logo"),
     ("Organic cotton, 180 g/m², regular fit.", "Bio-Baumwolle, 180 g/m², Regular Fit.",
      "Органический хлопок, 180 г/м², прямой крой."), 2990, 25, "S,M,L,XL", "tee_classic.png"),
    ("tees", ("Heavyweight Box Tee", "Heavyweight Box Tee", "Плотная футболка Box"),
     ("Boxy oversized cut, 260 g/m² heavy cotton.", "Boxy Oversized-Schnitt, 260 g/m² schwere Baumwolle.",
      "Свободный оверсайз, плотный хлопок 260 г/м²."), 3490, 12, "S,M,L,XL", "tee_box.png"),
    ("hoodies", ("Everyday Hoodie", "Everyday Hoodie", "Худи Everyday"),
     ("Brushed fleece inside, kangaroo pocket.", "Innen angeraut, Kängurutasche.",
      "Начёс внутри, карман-кенгуру."), 6490, 10, "S,M,L,XL", "hoodie.png"),
    ("hoodies", ("Zip Hoodie", "Zip Hoodie", "Худи на молнии"),
     ("Metal zip, ribbed cuffs. Restock soon.", "Metallreißverschluss, Rippbündchen. Bald wieder da.",
      "Металлическая молния, манжеты в рубчик. Скоро снова в наличии."), 6990, 0, "M,L,XL", "zip_hoodie.png"),
    ("accessories", ("Dad Cap", "Dad Cap", "Кепка Dad Cap"),
     ("Washed cotton, adjustable strap.", "Gewaschene Baumwolle, verstellbar.",
      "Стираный хлопок, регулируемый ремешок."), 2490, 30, "", "cap.png"),
    ("accessories", ("Canvas Tote", "Canvas Tote", "Сумка-шопер"),
     ("Heavy canvas, fits a laptop.", "Festes Canvas, passt ein Laptop rein.",
      "Плотный канвас, влезает ноутбук."), 1990, 40, "", "tote.png"),
    ("accessories", ("Sticker Pack", "Sticker-Set", "Набор стикеров"),
     ("8 vinyl stickers, waterproof.", "8 Vinyl-Sticker, wasserfest.", "8 виниловых стикеров, не боятся воды."),
     490, 100, "", "stickers.png"),
]


def now() -> int:
    return int(time.time())


class DB:
    def __init__(self, path: str = ":memory:", seed: bool = True) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        if seed:
            self.seed()

    # --- helpers -----------------------------------------------------------
    def all(self, sql: str, *args) -> list[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, *args) -> sqlite3.Row | None:
        return self.conn.execute(sql, args).fetchone()

    def seed(self) -> None:
        if self.one("SELECT 1 FROM categories LIMIT 1"):
            return
        with self.conn:
            for i, (slug, en, de, ru) in enumerate(SEED_CATEGORIES):
                self.conn.execute(
                    "INSERT INTO categories(slug,title_en,title_de,title_ru,sort) VALUES (?,?,?,?,?)",
                    (slug, en, de, ru, i))
        for slug, names, descs, price, stock, sizes, photo in SEED_PRODUCTS:
            cat = self.one("SELECT id FROM categories WHERE slug=?", slug)["id"]
            self.add_product(cat, names, descs, price, stock, sizes, photo_path=str(ASSETS / photo))

    # --- users -------------------------------------------------------------
    def ensure_user(self, user_id: int, first_name: str | None, username: str | None,
                    language_code: str | None, default_lang: str = "en") -> str:
        row = self.one("SELECT lang FROM users WHERE id=?", user_id)
        if row:
            self.conn.execute("UPDATE users SET first_name=?, username=? WHERE id=?",
                              (first_name, username, user_id))
            self.conn.commit()
            return row["lang"]
        lang = detect_lang(language_code, default_lang)
        with self.conn:
            self.conn.execute("INSERT INTO users(id,first_name,username,lang,created_at) VALUES (?,?,?,?,?)",
                              (user_id, first_name, username, lang, now()))
        return lang

    def set_lang(self, user_id: int, lang: str) -> None:
        if lang not in LANGS:
            raise ValueError(lang)
        with self.conn:
            self.conn.execute("UPDATE users SET lang=? WHERE id=?", (lang, user_id))

    def user_lang(self, user_id: int) -> str:
        row = self.one("SELECT lang FROM users WHERE id=?", user_id)
        return row["lang"] if row else "en"

    # --- catalog -----------------------------------------------------------
    def categories(self) -> list[sqlite3.Row]:
        return self.all("SELECT * FROM categories ORDER BY sort, id")

    def category(self, cat_id: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM categories WHERE id=?", cat_id)

    def products(self, category_id: int | None = None, active_only: bool = True) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM products WHERE 1=1", []
        if category_id is not None:
            sql += " AND category_id=?"
            args.append(category_id)
        if active_only:
            sql += " AND active=1"
        return self.all(sql + " ORDER BY id", *args)

    def product(self, product_id: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM products WHERE id=?", product_id)

    def add_product(self, category_id: int, names: tuple[str, str, str], descs: tuple[str, str, str],
                    price_cents: int, stock: int, sizes: str = "", photo_path: str | None = None,
                    photo_file_id: str | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO products(category_id,name_en,name_de,name_ru,desc_en,desc_de,desc_ru,"
                "price_cents,stock,sizes,photo_path,photo_file_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (category_id, *names, *descs, price_cents, stock, sizes, photo_path, photo_file_id, now()))
        return cur.lastrowid

    def change_stock(self, product_id: int, delta: int) -> int:
        with self.conn:
            self.conn.execute("UPDATE products SET stock=MAX(stock+?,0) WHERE id=?", (delta, product_id))
        return self.product(product_id)["stock"]

    def toggle_active(self, product_id: int) -> bool:
        with self.conn:
            self.conn.execute("UPDATE products SET active=1-active WHERE id=?", (product_id,))
        return bool(self.product(product_id)["active"])

    def set_photo_file_id(self, product_id: int, file_id: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE products SET photo_file_id=? WHERE id=?", (file_id, product_id))


def loc(row: sqlite3.Row, field: str, lang: str) -> str:
    """Localized column, falling back to English."""
    return row[f"{field}_{lang}"] or row[f"{field}_en"]


def sizes_of(row: sqlite3.Row) -> list[str]:
    return [s.strip() for s in (row["sizes"] or "").split(",") if s.strip()]
