"""Cart, orders, shipping, payment checks, status workflow, export and parsers — no Telegram."""
import re

import pytest

from store_bot import cart, orders
from store_bot.db import DB
from store_bot.export import CSV_FIELDS, orders_csv
from store_bot.handlers.admin import parse_i18n, parse_price, parse_sizes
from store_bot.i18n import LANGS, TEXTS, detect_lang, money

U = 42


@pytest.fixture
def db():
    d = DB(":memory:")
    d.ensure_user(U, "Anna", None, "en")
    return d


def pid(db, name):
    return db.one("SELECT id FROM products WHERE name_en=?", name)["id"]


# --- cart ----------------------------------------------------------------------
def test_add_merges_same_size_and_totals(db):
    tee, cap = pid(db, "Classic Logo Tee"), pid(db, "Dad Cap")
    cart.add_item(db, U, tee, "M")
    assert cart.add_item(db, U, tee, "M") == 2
    cart.add_item(db, U, tee, "L")
    cart.add_item(db, U, cap)
    view = cart.get_cart(db, U)
    assert [(ln.label, ln.qty) for ln in view.lines] == [
        ("Classic Logo Tee (L)", 1), ("Classic Logo Tee (M)", 2), ("Dad Cap", 1)]
    assert view.subtotal_cents == 3 * 2990 + 2490
    assert view.count == 4 == cart.count(db, U)


@pytest.mark.parametrize("name,size", [("Classic Logo Tee", ""), ("Classic Logo Tee", "XXL"), ("Dad Cap", "M")])
def test_size_is_validated(db, name, size):
    with pytest.raises(cart.CartError) as e:
        cart.add_item(db, U, pid(db, name), size)
    assert e.value.code == "bad_size"


def test_stock_is_shared_between_sizes(db):
    box = pid(db, "Heavyweight Box Tee")  # stock 12
    cart.add_item(db, U, box, "S", qty=10)
    cart.add_item(db, U, box, "M", qty=2)
    with pytest.raises(cart.CartError) as e:
        cart.add_item(db, U, box, "L")
    assert e.value.code == "out_of_stock"


def test_sold_out_and_hidden_products(db):
    with pytest.raises(cart.CartError) as e:
        cart.add_item(db, U, pid(db, "Zip Hoodie"), "M")  # stock 0
    assert e.value.code == "out_of_stock"
    cap = pid(db, "Dad Cap")
    cart.add_item(db, U, cap)
    db.toggle_active(cap)
    assert cart.get_cart(db, U).empty  # hidden product disappears from the cart view
    with pytest.raises(cart.CartError) as e:
        cart.add_item(db, U, cap)
    assert e.value.code == "unavailable"


def test_remove_and_clear(db):
    tee = pid(db, "Classic Logo Tee")
    cart.add_item(db, U, tee, "M", qty=2)
    assert cart.remove_item(db, U, tee, "M") == 1
    assert cart.remove_item(db, U, tee, "M") == 0
    assert cart.remove_item(db, U, tee, "M") == 0  # removing a missing line is harmless
    cart.add_item(db, U, tee, "S")
    cart.clear(db, U)
    assert cart.get_cart(db, U).empty


def test_localized_names_in_cart(db):
    cart.add_item(db, U, pid(db, "Sticker Pack"))
    assert cart.get_cart(db, U, "de").lines[0].name == "Sticker-Set"
    assert cart.get_cart(db, U, "ru").lines[0].name == "Набор стикеров"


# --- shipping -------------------------------------------------------------------------
def test_shipping_rates():
    assert [(r.id, r.cents) for r in orders.shipping_rates("DE", 7999)] == [("de_std", 490), ("de_express", 990)]
    assert orders.shipping_rates("de", 8000)[0].cents == 0  # free from 80 EUR
    assert [(r.id, r.cents) for r in orders.shipping_rates("AT", 100)] == [("eu_std", 990)]
    assert [(r.id, r.cents) for r in orders.shipping_rates("US", 100)] == [("world", 1990)]
    assert orders.shipping_rates("", 100) == []
    assert orders.shipping_cost("de_express", "FR", 100) is None  # option of another zone


# --- orders --------------------------------------------------------------------------
def make_order(db, user=U):
    db.ensure_user(user, "X", None, "en")
    cart.add_item(db, user, pid(db, "Classic Logo Tee"), "M", qty=2)
    cart.add_item(db, user, pid(db, "Dad Cap"))
    return orders.create_order(db, user, "en")


def test_create_order_snapshots_cart(db):
    with pytest.raises(orders.OrderError):
        orders.create_order(db, U, "en")
    oid = make_order(db)
    o = orders.get_order(db, oid)
    assert o["status"] == "new" and o["subtotal_cents"] == 2 * 2990 + 2490
    assert [(i["name"], i["size"], i["qty"]) for i in o["items"]] == [
        ("Classic Logo Tee", "M", 2), ("Dad Cap", "", 1)]
    assert orders.parse_payload(orders.payload_for(oid)) == oid
    assert orders.parse_payload("order:abc") is None and orders.parse_payload("x:1") is None


def test_new_checkout_supersedes_old_invoice(db):
    first = make_order(db)
    second = orders.create_order(db, U, "en")
    assert orders.get_order(db, first)["status"] == "cancelled"
    with pytest.raises(orders.OrderError) as e:
        orders.validate_pre_checkout(db, first, U, "EUR", 8470, "de_std", "DE")
    assert e.value.code == "order_changed"
    # 84.70 EUR >= 80 EUR: standard shipping in Germany is free, express is not
    assert orders.validate_pre_checkout(db, second, U, "EUR", 8470, "de_std", "DE") == 0
    assert orders.validate_pre_checkout(db, second, U, "EUR", 8470 + 990, "de_express", "DE") == 990


@pytest.mark.parametrize("kwargs,code", [
    ({"total_cents": 8470 + 490}, "order_changed"),                 # charged shipping that is free
    ({"shipping_option": "de_express", "country": "FR"}, "no_shipping"),
    ({"user_id": 999}, "not_yours"),
    ({"currency": "USD"}, "order_changed"),
])
def test_pre_checkout_rejects(db, kwargs, code):
    oid = make_order(db)
    args = dict(user_id=U, currency="EUR", total_cents=8470, shipping_option="de_std", country="DE")
    args.update(kwargs)
    with pytest.raises(orders.OrderError) as e:
        orders.validate_pre_checkout(db, oid, **args)
    assert e.value.code == code


def test_pre_checkout_rejects_if_sold_out_meanwhile(db):
    oid = make_order(db)
    db.change_stock(pid(db, "Dad Cap"), -1000)
    with pytest.raises(orders.OrderError) as e:
        orders.validate_pre_checkout(db, oid, U, "EUR", 8470, "de_std", "DE")
    assert e.value.code == "stock_changed"


def test_mark_paid_is_idempotent_and_updates_stock(db):
    tee = pid(db, "Classic Logo Tee")
    oid = make_order(db)
    info = {"name": "Anna", "phone": "+49", "country": "DE", "address": "Oranienstr. 25, 10999 Berlin, DE"}
    assert orders.mark_paid(db, oid, "ch_1", "pi_1", 9460, "de_express", info) is True
    assert orders.mark_paid(db, oid, "ch_1", "pi_1", 9460, "de_express", info) is False  # re-delivered update
    o = orders.get_order(db, oid)
    assert (o["status"], o["shipping_cents"], o["total_cents"], o["customer_name"]) == ("paid", 990, 9460, "Anna")
    assert db.product(tee)["stock"] == 23
    assert cart.get_cart(db, U).empty


def test_status_workflow(db):
    oid = make_order(db)
    with pytest.raises(orders.OrderError):
        orders.set_status(db, oid, "shipped", "admin")      # can't ship an unpaid order
    orders.mark_paid(db, oid, "ch_2", "pi_2", 8470, "de_std")
    with pytest.raises(orders.OrderError):
        orders.set_status(db, oid, "delivered", "admin")    # must pack and ship first
    for s in ("packed", "shipped", "delivered"):
        assert orders.set_status(db, oid, s, "admin")["status"] == s
    with pytest.raises(orders.OrderError):
        orders.set_status(db, oid, "cancelled", "admin")    # final state
    events = [r["status"] for r in db.all("SELECT status FROM order_events WHERE order_id=?", oid)]
    assert events == ["new", "paid", "packed", "shipped", "delivered"]


def test_cancel_paid_order_returns_stock(db):
    tee = pid(db, "Classic Logo Tee")
    oid = make_order(db)
    orders.mark_paid(db, oid, "ch_3", "pi_3", 8470, "de_std")
    assert db.product(tee)["stock"] == 23
    orders.set_status(db, oid, "cancelled", "admin")
    assert db.product(tee)["stock"] == 25
    assert orders.stats(db)["revenue_cents"] == 0


def test_csv_export(db):
    make_order(db)  # unpaid: not exported
    db.ensure_user(7, "Jürgen", None, "de")
    oid = make_order(db, user=7)
    orders.mark_paid(db, oid, "ch_4", "pi_4", 8470, "de_std",
                     {"name": "Jürgen Groß", "address": "Straße 1, 10115 Berlin, DE", "country": "DE"})
    data = orders_csv(db)
    assert data.startswith(b"\xef\xbb\xbf")  # BOM for Excel
    lines = data.decode("utf-8-sig").splitlines()
    assert lines[0] == ",".join(CSV_FIELDS) and len(lines) == 2
    assert "Jürgen Groß" in lines[1] and "Classic Logo Tee (M) x2; Dad Cap x1" in lines[1]


# --- admin parsers & i18n ----------------------------------------------------------------
def test_parsers():
    assert parse_price("29.90") == 2990 and parse_price("29,9") == 2990 and parse_price("30 €") == 3000
    assert parse_price("0") is None and parse_price("abc") is None and parse_price("-5") is None
    assert parse_sizes("s, m ,L") == "S,M,L" and parse_sizes("-") == ""
    assert parse_sizes("S,S") is None and parse_sizes("extra-large") is None
    assert parse_i18n("Beanie") == ("Beanie", "Beanie", "Beanie")
    assert parse_i18n("Beanie | Mütze | Шапка") == ("Beanie", "Mütze", "Шапка")
    assert parse_i18n("a | b") is None and parse_i18n("") is None


def test_every_text_has_all_languages_and_same_placeholders():
    for key, entry in TEXTS.items():
        assert set(entry) == set(LANGS), key
        ph = {lang: set(re.findall(r"{(\w+)}", entry[lang])) for lang in LANGS}
        assert ph["en"] == ph["de"] == ph["ru"], key


def test_detect_lang_and_money():
    assert detect_lang("de-AT") == "de" and detect_lang("uk") == "ru" and detect_lang("fr") == "en"
    assert money(2990, "en") == "€29.90" and money(2990, "de") == "29,90 €"
    assert money(123456, "ru") == "1 234,56 €"
