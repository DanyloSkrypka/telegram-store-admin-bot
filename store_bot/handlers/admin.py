"""Admin panel inside the bot (only for ADMIN_IDS): orders by status, status changes with
customer notifications, product management, add-product wizard and CSV export."""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import orders as orders_mod
from ..config import Settings
from ..db import DB, sizes_of
from ..export import SheetsSync, orders_csv
from ..i18n import money, t
from ..keyboards import Adm, b, kb

log = logging.getLogger(__name__)

STATUS_ICON = {"new": "⏳", "paid": "🟢", "packed": "📦", "shipped": "🚚", "delivered": "🏁", "cancelled": "❌"}
ACTION_LABEL = {"packed": "📦 Mark packed", "shipped": "🚚 Mark shipped", "delivered": "🏁 Mark delivered",
                "cancelled": "❌ Cancel order"}


class IsAdmin(Filter):
    async def __call__(self, event, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and settings.is_admin(user.id)


class AddProduct(StatesGroup):
    category = State()
    name = State()
    desc = State()
    price = State()
    stock = State()
    sizes = State()
    photo = State()


# --- pure parsers (unit-tested) ----------------------------------------------
def parse_i18n(text: str, max_len: int = 64) -> tuple[str, str, str] | None:
    """'Name' -> same in all languages; 'EN | DE | RU' -> per language."""
    parts = [p.strip() for p in (text or "").split("|")]
    if len(parts) == 1:
        parts = parts * 3
    if len(parts) != 3 or not all(parts) or any(len(p) > max_len for p in parts):
        return None
    return parts[0], parts[1], parts[2]


def parse_price(text: str) -> int | None:
    m = re.fullmatch(r"\s*(\d{1,6})(?:[.,](\d{1,2}))?\s*(?:€|eur)?\s*", (text or "").lower())
    if not m:
        return None
    cents = int(m.group(1)) * 100 + int((m.group(2) or "0").ljust(2, "0"))
    return cents if cents > 0 else None


def parse_sizes(text: str) -> str | None:
    raw = (text or "").strip()
    if raw in {"-", "—", "no", "none"}:
        return ""
    sizes = [s.strip().upper() for s in raw.split(",") if s.strip()]
    if not sizes or len(sizes) > 8 or any(not re.fullmatch(r"[A-Z0-9]{1,5}", s) for s in sizes):
        return None
    if len(set(sizes)) != len(sizes):
        return None
    return ",".join(sizes)


# --- texts ---------------------------------------------------------------------
def order_text(order: dict) -> str:
    cur = order["currency"]
    m = lambda c: money(c, "en", cur)  # noqa: E731
    lines = [f"{STATUS_ICON[order['status']]} <b>Order #{order['id']}</b> — {order['status'].upper()}", ""]
    for i in order["items"]:
        size = f" ({html.escape(i['size'])})" if i["size"] else ""
        lines.append(f"• {html.escape(i['name'])}{size} ×{i['qty']} — {m(i['price_cents'] * i['qty'])}")
    lines.append("")
    lines.append(f"Subtotal: {m(order['subtotal_cents'])}")
    if order["shipping_option"]:
        fee = m(order["shipping_cents"]) if order["shipping_cents"] else "free"
        lines.append(f"Shipping: {t('en', 'ship_' + order['shipping_option'])} — {fee}")
    lines.append(f"<b>Total: {m(order['total_cents'])}</b>")
    if order["customer_name"] or order["phone"]:
        lines.append(f"\n👤 {html.escape(order['customer_name'] or '')} · {html.escape(order['phone'] or '')}")
    if order["address"]:
        lines.append(f"📍 {html.escape(order['address'])}")
    lines.append(f"💬 <a href=\"tg://user?id={order['user_id']}\">Customer chat</a> · lang {order['lang'].upper()}")
    lines.append(f"🕒 {datetime.fromtimestamp(order['created_at']).strftime('%d.%m.%Y %H:%M')}")
    return "\n".join(lines)


def order_kb(order: dict):
    rows = [[b(ACTION_LABEL[s], Adm(action="status", id=order["id"], extra=s))]
            for s in orders_mod.ADMIN_NEXT[order["status"]]]
    rows.append([b("⬅️ Orders", Adm(action="orders", extra=order["status"])), b("🏠 Admin", Adm(action="home"))])
    return kb(rows)


async def notify_admins(bot: Bot, settings: Settings, order: dict) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, "🆕 <b>New paid order</b>\n\n" + order_text(order),
                                   reply_markup=order_kb(order))
        except Exception as exc:  # admin blocked the bot etc. — never break the payment flow
            log.warning("can't notify admin %s: %s", admin_id, exc)


def home_text(db: DB, settings: Settings) -> str:
    s = orders_mod.stats(db)
    c = s["counts"]
    return (f"🛠 <b>{html.escape(settings.shop_name)} — admin</b>\n\n"
            f"Revenue: <b>{money(s['revenue_cents'], 'en', settings.currency)}</b> · customers: {s['customers']}\n"
            f"To pack: <b>{c['paid']}</b> · to ship: <b>{c['packed']}</b> · on the way: {c['shipped']}")


def home_kb(db: DB):
    c = orders_mod.stats(db)["counts"]
    st = lambda s, label: b(f"{STATUS_ICON[s]} {label} ({c[s]})", Adm(action="orders", extra=s))  # noqa: E731
    return kb([
        [st("paid", "Paid"), st("packed", "Packed")],
        [st("shipped", "Shipped"), st("delivered", "Delivered")],
        [st("cancelled", "Cancelled")],
        [b("➕ Add product", Adm(action="add")), b("🗂 Products", Adm(action="products"))],
        [b("📤 Export CSV", Adm(action="export"))],
    ])


def product_admin_text(p, currency: str) -> str:
    state = "visible ✅" if p["active"] else "hidden 🚫"
    return (f"<b>#{p['id']} {html.escape(p['name_en'])}</b>\nDE: {html.escape(p['name_de'])} · "
            f"RU: {html.escape(p['name_ru'])}\n\nPrice: {money(p['price_cents'], 'en', currency)}\n"
            f"Stock: <b>{p['stock']}</b>\nSizes: {', '.join(sizes_of(p)) or 'one size'}\n"
            f"Photo: {'yes' if (p['photo_file_id'] or p['photo_path']) else 'no'}\nShop: {state}")


def product_admin_kb(p):
    pid = p["id"]
    return kb([
        [b("−1", Adm(action="stock", id=pid, extra="-1")), b("+1", Adm(action="stock", id=pid, extra="1")),
         b("+10", Adm(action="stock", id=pid, extra="10"))],
        [b("🚫 Hide from shop" if p["active"] else "✅ Show in shop", Adm(action="toggle", id=pid))],
        [b("⬅️ Products", Adm(action="products")), b("🏠 Admin", Adm(action="home"))],
    ])


async def edit(cb: CallbackQuery, text: str, markup=None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc):
            await cb.bot.send_message(cb.from_user.id, text, reply_markup=markup)


CANCEL_KB = kb([[b("✖️ Cancel", Adm(action="cancel"))]])


def get_router() -> Router:
    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())

    @router.message(Command("admin"))
    async def admin_cmd(message: Message, db: DB, settings: Settings, state: FSMContext) -> None:
        await state.clear()
        await message.answer(home_text(db, settings), reply_markup=home_kb(db))

    @router.callback_query(Adm.filter(F.action == "home"))
    async def home(cb: CallbackQuery, db: DB, settings: Settings) -> None:
        await edit(cb, home_text(db, settings), home_kb(db))
        await cb.answer()

    @router.callback_query(Adm.filter(F.action == "orders"))
    async def orders_list(cb: CallbackQuery, callback_data: Adm, db: DB) -> None:
        status = callback_data.extra or None
        rows = orders_mod.list_orders(db, status, limit=20)
        buttons = [[b(f"#{o['id']} · {money(o['total_cents'], 'en', o['currency'])} · "
                      f"{(o['customer_name'] or str(o['user_id']))[:18]}", Adm(action="order", id=o["id"]))]
                   for o in rows]
        buttons.append([b("🏠 Admin", Adm(action="home"))])
        title = f"{STATUS_ICON.get(status or '', '')} <b>Orders: {status or 'all'}</b>"
        await edit(cb, title + ("" if rows else "\n\nNo orders."), kb(buttons))
        await cb.answer()

    @router.callback_query(Adm.filter(F.action == "order"))
    async def order_card(cb: CallbackQuery, callback_data: Adm, db: DB) -> None:
        order = orders_mod.get_order(db, callback_data.id)
        if order is None:
            await cb.answer("Order not found", show_alert=True)
            return
        await edit(cb, order_text(order), order_kb(order))
        await cb.answer()

    @router.callback_query(Adm.filter(F.action == "status"))
    async def change_status(cb: CallbackQuery, callback_data: Adm, bot: Bot, db: DB, sheets: SheetsSync) -> None:
        try:
            order = orders_mod.set_status(db, callback_data.id, callback_data.extra, f"admin:{cb.from_user.id}")
        except orders_mod.OrderError as exc:
            await cb.answer(f"Not possible: {exc.code}", show_alert=True)
            return
        await edit(cb, order_text(order), order_kb(order))
        await cb.answer(f"Order #{order['id']} → {order['status']}")
        lang = db.user_lang(order["user_id"])
        try:
            await bot.send_message(order["user_id"], t(lang, "status_update", id=order["id"],
                                                       status=t(lang, "status_" + order["status"])))
        except Exception as exc:
            log.warning("can't notify customer %s: %s", order["user_id"], exc)
        sheets.schedule(order)

    # --- products --------------------------------------------------------------
    @router.callback_query(Adm.filter(F.action == "products"))
    async def products(cb: CallbackQuery, db: DB, settings: Settings) -> None:
        rows = [[b(f"{'✅' if p['active'] else '🚫'} {p['name_en']} · {p['stock']} pcs · "
                   f"{money(p['price_cents'], 'en', settings.currency)}", Adm(action="product", id=p["id"]))]
                for p in db.products(active_only=False)]
        rows.append([b("➕ Add product", Adm(action="add")), b("🏠 Admin", Adm(action="home"))])
        await edit(cb, "🗂 <b>Products</b> — tap to change stock or hide", kb(rows))
        await cb.answer()

    @router.callback_query(Adm.filter(F.action.in_({"product", "stock", "toggle"})))
    async def product(cb: CallbackQuery, callback_data: Adm, db: DB, settings: Settings) -> None:
        pid = callback_data.id
        if db.product(pid) is None:
            await cb.answer("Product not found", show_alert=True)
            return
        if callback_data.action == "stock":
            db.change_stock(pid, int(callback_data.extra))
        elif callback_data.action == "toggle":
            db.toggle_active(pid)
        p = db.product(pid)
        await edit(cb, product_admin_text(p, settings.currency), product_admin_kb(p))
        await cb.answer()

    # --- add product wizard ------------------------------------------------------
    @router.callback_query(Adm.filter(F.action == "add"))
    async def add_start(cb: CallbackQuery, db: DB, state: FSMContext) -> None:
        await state.clear()
        await state.set_state(AddProduct.category)
        rows = [[b(c["title_en"], Adm(action="addcat", id=c["id"]))] for c in db.categories()]
        rows.append([b("✖️ Cancel", Adm(action="cancel"))])
        await edit(cb, "➕ <b>New product</b> — step 1/7\nChoose a category:", kb(rows))
        await cb.answer()

    @router.callback_query(AddProduct.category, Adm.filter(F.action == "addcat"))
    async def add_category(cb: CallbackQuery, callback_data: Adm, state: FSMContext) -> None:
        await state.update_data(category_id=callback_data.id)
        await state.set_state(AddProduct.name)
        await edit(cb, "Step 2/7 — product <b>name</b>.\nOne name for all languages, or <code>EN | DE | RU</code>",
                   CANCEL_KB)
        await cb.answer()

    @router.callback_query(Adm.filter(F.action == "cancel"))
    async def add_cancel_cb(cb: CallbackQuery, db: DB, settings: Settings, state: FSMContext) -> None:
        await state.clear()
        await edit(cb, "Cancelled.\n\n" + home_text(db, settings), home_kb(db))
        await cb.answer()

    @router.message(StateFilter(AddProduct), Command("cancel"))
    async def add_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Cancelled. /admin")

    @router.message(AddProduct.name, F.text)
    async def add_name(message: Message, state: FSMContext) -> None:
        names = parse_i18n(message.text)
        if not names:
            await message.answer("❗ 1–64 characters, or three names separated by |", reply_markup=CANCEL_KB)
            return
        await state.update_data(names=names)
        await state.set_state(AddProduct.desc)
        await message.answer("Step 3/7 — <b>description</b> (one text or <code>EN | DE | RU</code>), "
                             "or <code>-</code> to skip", reply_markup=CANCEL_KB)

    @router.message(AddProduct.desc, F.text)
    async def add_desc(message: Message, state: FSMContext) -> None:
        if message.text.strip() == "-":
            descs = ("", "", "")
        else:
            descs = parse_i18n(message.text, max_len=500)
            if not descs:
                await message.answer("❗ Up to 500 characters per language", reply_markup=CANCEL_KB)
                return
        await state.update_data(descs=descs)
        await state.set_state(AddProduct.price)
        await message.answer("Step 4/7 — <b>price</b> in EUR, e.g. <code>29.90</code>", reply_markup=CANCEL_KB)

    @router.message(AddProduct.price, F.text)
    async def add_price(message: Message, state: FSMContext) -> None:
        cents = parse_price(message.text)
        if cents is None:
            await message.answer("❗ Send a price like 29.90 or 29,90", reply_markup=CANCEL_KB)
            return
        await state.update_data(price_cents=cents)
        await state.set_state(AddProduct.stock)
        await message.answer("Step 5/7 — <b>stock</b> (pieces), e.g. <code>20</code>", reply_markup=CANCEL_KB)

    @router.message(AddProduct.stock, F.text)
    async def add_stock(message: Message, state: FSMContext) -> None:
        raw = message.text.strip()
        if not raw.isdigit() or int(raw) > 100000:
            await message.answer("❗ A whole number from 0", reply_markup=CANCEL_KB)
            return
        await state.update_data(stock=int(raw))
        await state.set_state(AddProduct.sizes)
        await message.answer("Step 6/7 — <b>sizes</b> separated by commas, e.g. <code>S,M,L,XL</code>, "
                             "or <code>-</code> for one size", reply_markup=CANCEL_KB)

    @router.message(AddProduct.sizes, F.text)
    async def add_sizes(message: Message, state: FSMContext) -> None:
        sizes = parse_sizes(message.text)
        if sizes is None:
            await message.answer("❗ Like S,M,L (letters/digits, up to 8 sizes) or -", reply_markup=CANCEL_KB)
            return
        await state.update_data(sizes=sizes)
        await state.set_state(AddProduct.photo)
        await message.answer("Step 7/7 — send a <b>photo</b>, or /skip", reply_markup=CANCEL_KB)

    async def save(message: Message, db: DB, settings: Settings, state: FSMContext, file_id: str | None) -> None:
        d = await state.get_data()
        pid = db.add_product(d["category_id"], tuple(d["names"]), tuple(d["descs"]), d["price_cents"],
                             d["stock"], d["sizes"], photo_file_id=file_id)
        await state.clear()
        p = db.product(pid)
        await message.answer("✅ Product added and live in the shop.\n\n" + product_admin_text(p, settings.currency),
                             reply_markup=product_admin_kb(p))

    @router.message(AddProduct.photo, F.photo)
    async def add_photo(message: Message, db: DB, settings: Settings, state: FSMContext) -> None:
        await save(message, db, settings, state, message.photo[-1].file_id)

    @router.message(AddProduct.photo, Command("skip"))
    async def add_skip(message: Message, db: DB, settings: Settings, state: FSMContext) -> None:
        await save(message, db, settings, state, None)

    @router.message(StateFilter(AddProduct))
    async def add_wrong(message: Message) -> None:
        await message.answer("❗ Please follow the step above, or /cancel")

    # --- export ------------------------------------------------------------------
    @router.callback_query(Adm.filter(F.action == "export"))
    async def export(cb: CallbackQuery, bot: Bot, db: DB, sheets: SheetsSync) -> None:
        data = orders_csv(db)
        n = data.decode("utf-8-sig").count("\n") - 1
        caption = f"📤 {n} paid orders" + (" · Google Sheets live sync: ON" if sheets.enabled else "")
        await bot.send_document(cb.from_user.id, BufferedInputFile(
            data, filename=f"orders_{datetime.now():%Y-%m-%d}.csv"), caption=caption)
        await cb.answer()

    return router
