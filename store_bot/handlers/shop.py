"""Customer side: menu, catalog, product cards, cart, checkout and Telegram Payments."""
from __future__ import annotations

import html
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, FSInputFile, LabeledPrice, Message, PreCheckoutQuery, ShippingOption, ShippingQuery,
)

from .. import cart as cart_mod
from .. import keyboards as K
from .. import orders as orders_mod
from ..config import Settings
from ..db import DB, loc, sizes_of
from ..export import SheetsSync
from ..i18n import money, t
from ..keyboards import Nav
from .admin import notify_admins

log = logging.getLogger(__name__)

ERR_KEYS = {"stock_changed": "err_stock_changed", "no_shipping": "err_no_shipping"}


def order_err(lang: str, code: str) -> str:
    return t(lang, ERR_KEYS.get(code, "err_order_changed"))


async def show(cb: CallbackQuery, text: str, markup=None) -> None:
    """Replace the message the button belongs to. Photo/invoice messages can't become text,
    so they are deleted and a new message is sent."""
    msg = cb.message
    if isinstance(msg, Message) and not msg.photo and msg.text is not None:
        try:
            await msg.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc):
                return
    if isinstance(msg, Message):
        try:
            await msg.delete()
        except TelegramBadRequest:
            pass
    await cb.bot.send_message(cb.from_user.id, text, reply_markup=markup)


def cart_text(lang: str, view: cart_mod.CartView, settings: Settings) -> str:
    if view.empty:
        return f"{t(lang, 'cart_title')}\n\n{t(lang, 'cart_empty')}"
    cur = settings.currency
    lines = [f"{n}. {html.escape(ln.label)} × {ln.qty} — {money(ln.total_cents, lang, cur)}"
             for n, ln in enumerate(view.lines, 1)]
    return (f"{t(lang, 'cart_title')}\n\n" + "\n".join(lines) + "\n\n"
            + t(lang, "subtotal", sum=money(view.subtotal_cents, lang, cur)) + "\n<i>"
            + t(lang, "shipping_note", free=money(settings.free_shipping_de_cents, lang, cur)) + "</i>")


def product_text(lang: str, p, settings: Settings) -> str:
    stock = t(lang, "in_stock", n=p["stock"]) if p["stock"] > 0 else f"❌ {t(lang, 'sold_out')}"
    text = (f"<b>{html.escape(loc(p, 'name', lang))}</b>\n{html.escape(loc(p, 'desc', lang))}\n\n"
            f"💶 <b>{money(p['price_cents'], lang, settings.currency)}</b> · {stock}")
    if p["stock"] > 0 and sizes_of(p):
        text += f"\n\n{t(lang, 'pick_size')}"
    return text


def get_router() -> Router:
    router = Router(name="shop")

    async def send_menu(bot: Bot, chat_id: int, db: DB, lang: str, text: str) -> None:
        await bot.send_message(chat_id, text, reply_markup=K.main_menu(lang, cart_mod.count(db, chat_id)))

    @router.message(CommandStart())
    async def start(message: Message, bot: Bot, db: DB, settings: Settings, lang: str) -> None:
        name = html.escape(message.from_user.first_name or "")
        await send_menu(bot, message.chat.id, db, lang, t(lang, "welcome", name=name, shop=settings.shop_name))

    @router.message(Command("language"))
    async def language_cmd(message: Message, lang: str) -> None:
        await message.answer(t(lang, "choose_lang"), reply_markup=K.lang_picker())

    @router.callback_query(Nav.filter(F.action == "lang"))
    async def language(cb: CallbackQuery, callback_data: Nav, db: DB) -> None:
        uid = cb.from_user.id
        if not callback_data.extra:
            await show(cb, t(db.user_lang(uid), "choose_lang"), K.lang_picker())
        else:
            db.set_lang(uid, callback_data.extra)
            lang = callback_data.extra
            await show(cb, f"{t(lang, 'lang_set')}\n\n{t(lang, 'menu')}", K.main_menu(lang, cart_mod.count(db, uid)))
        await cb.answer()

    @router.callback_query(Nav.filter(F.action == "menu"))
    async def menu(cb: CallbackQuery, db: DB, lang: str) -> None:
        await show(cb, t(lang, "menu"), K.main_menu(lang, cart_mod.count(db, cb.from_user.id)))
        await cb.answer()

    @router.callback_query(Nav.filter(F.action == "cats"))
    async def cats(cb: CallbackQuery, db: DB, lang: str) -> None:
        await show(cb, t(lang, "categories"), K.categories(lang, db.categories(), cart_mod.count(db, cb.from_user.id)))
        await cb.answer()

    @router.callback_query(Nav.filter(F.action == "cat"))
    async def category(cb: CallbackQuery, callback_data: Nav, db: DB, settings: Settings, lang: str) -> None:
        cat = db.category(callback_data.id)
        items = db.products(callback_data.id) if cat else []
        title = f"<b>{html.escape(loc(cat, 'title', lang))}</b>" if cat else ""
        body = title if items else f"{title}\n{t(lang, 'category_empty')}"
        await show(cb, body, K.products(lang, items, settings.currency))
        await cb.answer()

    @router.callback_query(Nav.filter(F.action == "prod"))
    async def product(cb: CallbackQuery, callback_data: Nav, bot: Bot, db: DB, settings: Settings, lang: str) -> None:
        p = db.product(callback_data.id)
        if p is None or not p["active"]:
            await cb.answer(t(lang, "err_unavailable"), show_alert=True)
            return
        uid = cb.from_user.id
        text, markup = product_text(lang, p, settings), K.product_card(lang, p, cart_mod.count(db, uid))
        photo = p["photo_file_id"] or (FSInputFile(p["photo_path"]) if p["photo_path"] else None)
        if isinstance(cb.message, Message):
            try:
                await cb.message.delete()
            except TelegramBadRequest:
                pass
        if photo is None:
            await bot.send_message(uid, text, reply_markup=markup)
        else:
            sent = await bot.send_photo(uid, photo, caption=text, reply_markup=markup)
            if not p["photo_file_id"] and sent.photo:  # upload once, then reuse Telegram's file_id
                db.set_photo_file_id(p["id"], sent.photo[-1].file_id)
        await cb.answer()

    @router.callback_query(Nav.filter(F.action.in_({"add", "inc"})))
    async def add(cb: CallbackQuery, callback_data: Nav, db: DB, settings: Settings, lang: str) -> None:
        uid = cb.from_user.id
        try:
            cart_mod.add_item(db, uid, callback_data.id, callback_data.extra)
        except cart_mod.CartError as exc:
            await cb.answer(t(lang, f"err_{exc.code}"), show_alert=True)
            return
        p = db.product(callback_data.id)
        label = loc(p, "name", lang) + (f" ({callback_data.extra})" if callback_data.extra else "")
        await cb.answer(t(lang, "added", item=label))
        if callback_data.action == "inc":
            await render_cart(cb, db, lang, settings)
        elif isinstance(cb.message, Message):
            try:
                await cb.message.edit_reply_markup(reply_markup=K.product_card(lang, p, cart_mod.count(db, uid)))
            except TelegramBadRequest:
                pass

    async def render_cart(cb: CallbackQuery, db: DB, lang: str, settings: Settings) -> None:
        view = cart_mod.get_cart(db, cb.from_user.id, lang)
        await show(cb, cart_text(lang, view, settings), K.cart(lang, view))

    @router.callback_query(Nav.filter(F.action == "cart"))
    async def cart(cb: CallbackQuery, db: DB, settings: Settings, lang: str) -> None:
        await render_cart(cb, db, lang, settings)
        await cb.answer()

    @router.callback_query(Nav.filter(F.action == "dec"))
    async def dec(cb: CallbackQuery, callback_data: Nav, db: DB, settings: Settings, lang: str) -> None:
        cart_mod.remove_item(db, cb.from_user.id, callback_data.id, callback_data.extra)
        await render_cart(cb, db, lang, settings)
        await cb.answer()

    @router.callback_query(Nav.filter(F.action == "clear"))
    async def clear(cb: CallbackQuery, db: DB, settings: Settings, lang: str) -> None:
        cart_mod.clear(db, cb.from_user.id)
        await render_cart(cb, db, lang, settings)
        await cb.answer(t(lang, "cart_cleared"))

    @router.callback_query(Nav.filter(F.action == "checkout"))
    async def checkout(cb: CallbackQuery, bot: Bot, db: DB, settings: Settings, lang: str) -> None:
        uid = cb.from_user.id
        if not settings.provider_token and not settings.test_mode:
            await cb.answer(t(lang, "pay_not_configured"), show_alert=True)
            return
        try:
            order_id = orders_mod.create_order(db, uid, lang, settings.currency)
        except orders_mod.OrderError as exc:
            key = "err_stock_changed" if exc.code == "stock_changed" else "cart_empty"
            await cb.answer(t(lang, key), show_alert=True)
            return
        order = orders_mod.get_order(db, order_id)
        hint = t(lang, "checkout_hint", id=order_id)
        if settings.payments_test:
            hint += "\n\n" + t(lang, "test_card")
        await show(cb, hint, None)
        items = ", ".join(f"{i['name']}{' ' + i['size'] if i['size'] else ''} ×{i['qty']}" for i in order["items"])
        await bot.send_invoice(
            chat_id=uid,
            title=t(lang, "invoice_title", shop=settings.shop_name, id=order_id)[:32],
            description=t(lang, "invoice_desc", items=items)[:255],
            payload=orders_mod.payload_for(order_id),
            provider_token=settings.provider_token or "TEST:emulator",
            currency=settings.currency,
            prices=[LabeledPrice(label=f"{i['name']}{' ' + i['size'] if i['size'] else ''} ×{i['qty']}"[:32],
                                 amount=i["price_cents"] * i["qty"]) for i in order["items"]],
            need_name=True, need_phone_number=True, need_shipping_address=True, is_flexible=True,
        )
        await cb.answer()

    @router.shipping_query()
    async def shipping(query: ShippingQuery, db: DB, settings: Settings, lang: str) -> None:
        try:
            rates = orders_mod.validate_shipping(
                db, orders_mod.parse_payload(query.invoice_payload), query.from_user.id, settings.currency,
                query.shipping_address.country_code, settings.free_shipping_de_cents)
        except orders_mod.OrderError as exc:
            await query.answer(ok=False, error_message=order_err(lang, exc.code))
            return
        await query.answer(ok=True, shipping_options=[
            ShippingOption(id=r.id, title=t(lang, f"ship_{r.id}"),
                           prices=[LabeledPrice(label=t(lang, f"ship_{r.id}"), amount=r.cents)])
            for r in rates])

    @router.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery, db: DB, settings: Settings, lang: str) -> None:
        addr = query.order_info.shipping_address if query.order_info else None
        try:
            orders_mod.validate_pre_checkout(
                db, orders_mod.parse_payload(query.invoice_payload), query.from_user.id, query.currency,
                query.total_amount, query.shipping_option_id, addr.country_code if addr else None,
                settings.free_shipping_de_cents)
        except orders_mod.OrderError as exc:
            log.info("pre-checkout rejected for %s: %s", query.from_user.id, exc.code)
            await query.answer(ok=False, error_message=order_err(lang, exc.code))
            return
        await query.answer(ok=True)

    @router.message(F.successful_payment)
    async def paid(message: Message, bot: Bot, db: DB, settings: Settings, sheets: SheetsSync, lang: str) -> None:
        sp = message.successful_payment
        order_id = orders_mod.parse_payload(sp.invoice_payload)
        info: dict = {}
        if sp.order_info:
            oi = sp.order_info
            info = {"name": oi.name, "phone": oi.phone_number, "email": oi.email}
            if oi.shipping_address:
                a = oi.shipping_address
                info["country"] = a.country_code
                info["address"] = ", ".join(x for x in [a.street_line1, a.street_line2,
                                                        f"{a.post_code} {a.city}".strip(), a.state,
                                                        a.country_code] if x)
        if order_id is None or not orders_mod.mark_paid(
                db, order_id, sp.telegram_payment_charge_id, sp.provider_payment_charge_id,
                sp.total_amount, sp.shipping_option_id, info):
            log.warning("payment not applied (duplicate or unknown order): %s", sp.invoice_payload)
            return
        order = orders_mod.get_order(db, order_id)
        await send_menu(bot, message.chat.id, db, lang,
                        t(lang, "paid_thanks", id=order_id, sum=money(order["total_cents"], lang, order["currency"])))
        await notify_admins(bot, settings, order)
        sheets.schedule(order)

    @router.callback_query(Nav.filter(F.action == "orders"))
    async def my_orders(cb: CallbackQuery, db: DB, lang: str) -> None:
        rows = orders_mod.user_orders(db, cb.from_user.id)
        if not rows:
            body = f"{t(lang, 'orders_title')}\n\n{t(lang, 'orders_empty')}"
        else:
            body = t(lang, "orders_title") + "\n\n" + "\n".join(
                f"#{o['id']} · {datetime.fromtimestamp(o['created_at']).strftime('%d.%m')} · "
                f"{money(o['total_cents'], lang, o['currency'])} — {t(lang, 'status_' + o['status'])}" for o in rows)
        await show(cb, body, K.back_to_menu(lang))
        await cb.answer()

    return router


def get_fallback_router() -> Router:
    router = Router(name="fallback")

    @router.message()
    async def unknown(message: Message, db: DB, lang: str) -> None:
        await message.answer(t(lang, "unknown"), reply_markup=K.main_menu(lang, cart_mod.count(db, message.chat.id)))

    return router
