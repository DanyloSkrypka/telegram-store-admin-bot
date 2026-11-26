"""End-to-end: the real aiogram handlers driven through the offline Telegram emulator."""
from pathlib import Path

import pytest

from store_bot.config import Settings
from store_bot.emulator import ADMIN_ID, Harness, plain
from store_bot.export import SheetsSync

ASSET = str(Path(__file__).resolve().parent.parent / "assets" / "products" / "new_beanie.png")


@pytest.fixture
def pushed():
    return []


@pytest.fixture
def h(pushed):
    async def poster(url, body):
        pushed.append(body)

    return Harness(sheets=SheetsSync("https://script.google.com/macros/s/TEST/exec", "s3cret", poster=poster))


async def buy(h, u, country="DE"):
    await h.send(u, "/start")
    for label in ["🛍", "T-shirts", "Classic Logo Tee", "M"]:
        await h.press(u, label)
    await h.press(u, "🛒")
    await h.press(u, "➕")          # second Classic Logo Tee (M)
    await h.press(u, "✅")
    return await h.pay(u, country=country)


async def test_full_purchase_admin_and_status_updates(h, pushed):
    u, admin = h.user(42, "Anna"), h.user(ADMIN_ID, "Owner")
    res = await buy(h, u)
    assert res["pre_checkout_ok"] and res["total"] == 2 * 2990 + 490 and res["option"] == "de_std"
    assert "Thank you! Order #1 is paid: €64.70" in plain(h.last(42).text)
    alert = plain(h.last(ADMIN_ID).text)
    assert "New paid order" in alert and "Classic Logo Tee (M) ×2" in alert and "Oranienstr. 25" in alert
    for label, status in [("📦 Mark packed", "packed 📦"), ("🚚 Mark shipped", "shipped 🚚"),
                          ("🏁 Mark delivered", "delivered 🏁")]:
        assert await h.press(admin, label) == f"Order #1 → {status.split()[0]}"
        assert plain(h.last(42).text) == f"🔔 Order #1: {status}"
    await h.sheets.drain()
    assert [p["row"]["status"] for p in pushed] == ["paid", "packed", "shipped", "delivered"]
    assert pushed[0]["secret"] == "s3cret" and pushed[0]["row"]["total"] == "64.70"


async def test_shipping_zones_change_total(h):
    res = await buy(h, h.user(43), country="US")
    assert res["options"] == [("world", "Worldwide (7–14 days)", 1990)]
    assert res["total"] == 2 * 2990 + 1990


async def test_duplicate_payment_update_notifies_once(h):
    u = h.user(42)
    res = await buy(h, u)
    admin_msgs = len(h.session.chat(ADMIN_ID))
    from aiogram.types import Message, SuccessfulPayment, Update, Chat
    import time
    sp = SuccessfulPayment(currency="EUR", total_amount=res["total"], invoice_payload="order:1",
                           shipping_option_id="de_std", telegram_payment_charge_id=res["charge_id"],
                           provider_payment_charge_id="pi")
    await h.feed(Update(update_id=999, message=Message(message_id=999, date=int(time.time()),
                                                       chat=Chat(id=42, type="private"), from_user=u,
                                                       successful_payment=sp)))
    assert len(h.session.chat(ADMIN_ID)) == admin_msgs


async def test_sold_out_between_invoice_and_payment(h):
    u = h.user(44, lang="de")
    await h.send(u, "/start")
    for label in ["🛍", "Accessoires", "Dad Cap", "➕", "🛒", "✅"]:
        await h.press(u, label)
    h.db.change_stock(h.db.one("SELECT id FROM products WHERE name_en='Dad Cap'")["id"], -1000)
    res = await h.pay(u)
    assert res["pre_checkout_ok"] is False
    assert res["error"] == "Einige Artikel sind gerade ausverkauft. Bitte prüfe den Warenkorb."
    assert h.db.one("SELECT status FROM orders WHERE id=1")["status"] == "new"


async def test_language_autodetect_and_switch(h):
    u = h.user(50, "Lukas", lang="de")
    await h.send(u, "/start")
    assert "Willkommen bei" in h.last(50).text
    assert h.last(50).buttons[0][0]["text"] == "🛍 Katalog"
    await h.press(u, "🌐")
    await h.press(u, "🇷🇺 Русский")
    assert h.last(50).buttons[0][0]["text"] == "🛍 Каталог"
    await h.press(u, "🛍")
    assert [r[0]["text"] for r in h.last(50).buttons[:3]] == ["Футболки", "Худи", "Аксессуары"]


async def test_sold_out_product_has_no_buy_buttons(h):
    u = h.user(51)
    await h.send(u, "/start")
    for label in ["🛍", "Hoodies"]:
        await h.press(u, label)
    assert "Zip Hoodie · sold out" in [r[0]["text"] for r in h.last(51).buttons]
    await h.press(u, "Zip Hoodie")
    card = h.last(51)
    assert card.kind == "photo" and "sold out" in card.text
    assert [b["text"] for row in card.buttons for b in row] == ["🛒 Cart (0)", "⬅️ Back"]


async def test_admin_panel_is_private(h):
    stranger = h.user(60)
    await h.send(stranger, "/admin")
    assert h.last(60).text == "Use the buttons below 👇"
    await h.send(h.user(ADMIN_ID), "/admin")
    assert "admin" in h.last(ADMIN_ID).text and "Revenue" in h.last(ADMIN_ID).text


async def test_admin_adds_product_with_photo(h):
    a = h.user(ADMIN_ID, "Owner")
    await h.send(a, "/admin")
    await h.press(a, "➕ Add product")
    await h.press(a, "Accessories")
    await h.send(a, "Beanie | Mütze | Шапка")
    await h.send(a, "Rib knit, one size.")
    await h.send(a, "free")                       # invalid price -> asked again
    assert "❗" in h.last(ADMIN_ID).text
    await h.send(a, "19,90")
    await h.send(a, "15")
    await h.send(a, "-")
    await h.send_photo(a, ASSET)
    assert "Product added" in h.last(ADMIN_ID).text and "€19.90" in h.last(ADMIN_ID).text
    # customer sees it, in German, with the uploaded photo
    c = h.user(70, lang="de")
    await h.send(c, "/start")
    for label in ["🛍", "Accessoires", "Mütze"]:
        await h.press(c, label)
    card = h.last(70)
    assert card.kind == "photo" and card.photo == ASSET and "19,90 €" in card.text


async def test_admin_stock_hide_and_export(h):
    a = h.user(ADMIN_ID)
    await buy(h, h.user(42))
    await h.send(a, "/admin")
    await h.press(a, "🗂 Products")
    await h.press(a, "✅ Dad Cap")
    await h.press(a, "+10")
    assert "Stock: 40" in plain(h.last(ADMIN_ID).text)
    await h.press(a, "🚫 Hide from shop")
    assert h.db.one("SELECT active FROM products WHERE name_en='Dad Cap'")["active"] == 0
    await h.press(a, "🏠 Admin")
    await h.press(a, "📤 Export CSV")
    doc = h.last(ADMIN_ID)
    assert doc.kind == "document" and doc.extra["filename"].startswith("orders_")
    assert "Classic Logo Tee (M) x2" in doc.extra["data"].decode("utf-8-sig")
    assert "1 paid orders" in doc.text and "Sheets live sync: ON" in doc.text


async def test_checkout_refused_when_payments_not_configured():
    h = Harness(settings=Settings(bot_token="1:real", admin_ids=frozenset({ADMIN_ID}), provider_token=None))
    u = h.user(80)
    await h.send(u, "/start")
    for label in ["🛍", "Accessories", "Canvas Tote", "➕", "🛒"]:
        await h.press(u, label)
    assert await h.press(u, "✅") == "Payments are not configured yet. Please contact the shop."
    assert h.db.one("SELECT COUNT(*) n FROM orders")["n"] == 0
