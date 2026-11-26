"""Inline keyboards and callback data."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup

from .cart import CartView
from .db import loc, sizes_of
from .i18n import LANG_NAMES, LANGS, money, t


class Nav(CallbackData, prefix="n"):
    action: str
    id: int = 0
    extra: str = ""


class Adm(CallbackData, prefix="a"):
    action: str
    id: int = 0
    extra: str = ""


def kb(rows: list[list[Btn]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def b(text: str, data: CallbackData) -> Btn:
    return Btn(text=text, callback_data=data.pack())


def main_menu(lang: str, cart_count: int) -> InlineKeyboardMarkup:
    return kb([
        [b(t(lang, "btn_catalog"), Nav(action="cats"))],
        [b(t(lang, "btn_cart", n=cart_count), Nav(action="cart")),
         b(t(lang, "btn_orders"), Nav(action="orders"))],
        [b(t(lang, "btn_lang"), Nav(action="lang"))],
    ])


def lang_picker() -> InlineKeyboardMarkup:
    return kb([[b(LANG_NAMES[code], Nav(action="lang", extra=code)) for code in LANGS]])


def categories(lang: str, cats, cart_count: int) -> InlineKeyboardMarkup:
    rows = [[b(loc(c, "title", lang), Nav(action="cat", id=c["id"]))] for c in cats]
    rows.append([b(t(lang, "btn_cart", n=cart_count), Nav(action="cart")), b(t(lang, "btn_menu"), Nav(action="menu"))])
    return kb(rows)


def products(lang: str, items, currency: str) -> InlineKeyboardMarkup:
    rows = []
    for p in items:
        price = money(p["price_cents"], lang, currency)
        tail = price if p["stock"] > 0 else t(lang, "sold_out")
        rows.append([b(f"{loc(p, 'name', lang)} · {tail}", Nav(action="prod", id=p["id"]))])
    rows.append([b(t(lang, "btn_back"), Nav(action="cats"))])
    return kb(rows)


def product_card(lang: str, p, cart_count: int) -> InlineKeyboardMarkup:
    rows: list[list[Btn]] = []
    if p["stock"] > 0:
        sizes = sizes_of(p)
        if sizes:
            rows.append([b(s, Nav(action="add", id=p["id"], extra=s)) for s in sizes])
        else:
            rows.append([b(t(lang, "btn_add"), Nav(action="add", id=p["id"]))])
    rows.append([b(t(lang, "btn_cart", n=cart_count), Nav(action="cart")),
                 b(t(lang, "btn_back"), Nav(action="cat", id=p["category_id"]))])
    return kb(rows)


def cart(lang: str, view: CartView) -> InlineKeyboardMarkup:
    rows = []
    for n, ln in enumerate(view.lines, 1):  # numbers match the numbered lines in the cart text
        rows.append([b("➖", Nav(action="dec", id=ln.product_id, extra=ln.size)),
                     b(f"{n}. {ln.size + ' ' if ln.size else ''}×{ln.qty}", Nav(action="prod", id=ln.product_id)),
                     b("➕", Nav(action="inc", id=ln.product_id, extra=ln.size))])
    if not view.empty:
        rows.append([b(t(lang, "btn_clear"), Nav(action="clear")), b(t(lang, "btn_checkout"), Nav(action="checkout"))])
    rows.append([b(t(lang, "btn_catalog"), Nav(action="cats")), b(t(lang, "btn_menu"), Nav(action="menu"))])
    return kb(rows)


def back_to_menu(lang: str) -> InlineKeyboardMarkup:
    return kb([[b(t(lang, "btn_menu"), Nav(action="menu"))]])
