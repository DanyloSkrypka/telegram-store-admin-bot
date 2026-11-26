"""Offline Telegram emulator.

A fake Bot API session records every outgoing call and returns plausible results, so the real
aiogram handlers run unchanged without a token or network. `Harness` builds incoming updates
(messages, button taps, photos, shipping/pre-checkout queries, payments). Used by pytest, the
scripted demo and the interactive console.
"""
from __future__ import annotations

import copy
import itertools
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery, AnswerPreCheckoutQuery, AnswerShippingQuery, DeleteMessage, EditMessageReplyMarkup,
    EditMessageText, SendDocument, SendInvoice, SendMessage, SendPhoto, TelegramMethod,
)
from aiogram.types import (
    CallbackQuery, Chat, Document, FSInputFile, InlineKeyboardMarkup, Message, OrderInfo, PhotoSize,
    PreCheckoutQuery, ShippingAddress, ShippingQuery, SuccessfulPayment, Update, User,
)

from .bot import build_dispatcher, default_props
from .config import Settings
from .db import DB
from .export import SheetsSync

BOT_USER = User(id=7000000001, is_bot=True, first_name="KIEZ Supply", username="kiez_supply_bot")
ADMIN_ID = 1001
TAG = re.compile(r"<[^>]+>")


def plain(text: str | None) -> str:
    return TAG.sub("", text or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')


def _buttons(markup) -> list[list[dict]]:
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [[{"text": b.text, "data": b.callback_data} for b in row] for row in markup.inline_keyboard]


@dataclass
class Item:
    """One message on a chat screen."""
    who: str                      # bot | user | system
    kind: str                     # text | photo | invoice | document | payment
    text: str = ""
    buttons: list = field(default_factory=list)
    photo: str | None = None      # local path for rendering
    mid: int = 0
    extra: dict = field(default_factory=dict)
    deleted: bool = False


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, Any]] = []
        self.chats: dict[int, list[Item]] = {}
        self.toasts: list[tuple[int, str, bool]] = []
        self.shipping_answers: list[AnswerShippingQuery] = []
        self.pre_checkout_answers: list[AnswerPreCheckoutQuery] = []
        self.file_paths: dict[str, str] = {}
        self.events: dict[int, list[tuple[str, Item]]] = {}   # chronological log for transcripts
        self._mid = itertools.count(5000)
        self._fid = itertools.count(1)

    async def close(self) -> None:
        pass

    async def stream_content(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    def chat(self, chat_id: int) -> list[Item]:
        return self.chats.setdefault(chat_id, [])

    def add(self, chat_id: int, item: Item) -> Item:
        self.chat(chat_id).append(item)
        self.events.setdefault(chat_id, []).append(("new", copy.deepcopy(item)))
        return item

    def edited(self, chat_id: int, item: Item) -> None:
        self.events.setdefault(chat_id, []).append(("edit", copy.deepcopy(item)))

    def find(self, chat_id: int, mid: int) -> Item | None:
        return next((i for i in self.chat(chat_id) if i.who == "bot" and i.mid == mid and not i.deleted), None)

    def _msg(self, chat_id: int, mid: int, **extra) -> Message:
        return Message(message_id=mid, date=int(time.time()), chat=Chat(id=chat_id, type="private"),
                       from_user=BOT_USER, **extra)

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.calls.append((type(method).__name__, method))
        chat_id = getattr(method, "chat_id", None)
        if isinstance(method, SendMessage):
            mid = next(self._mid)
            self.add(chat_id, Item("bot", "text", method.text, _buttons(method.reply_markup), mid=mid))
            return self._msg(chat_id, mid, text=method.text, reply_markup=method.reply_markup)
        if isinstance(method, SendPhoto):
            mid, photo = next(self._mid), method.photo
            if isinstance(photo, FSInputFile):
                file_id = f"photo-{next(self._fid)}"
                self.file_paths[file_id] = str(photo.path)
            else:
                file_id = str(photo)
            self.add(chat_id, Item("bot", "photo", method.caption or "", _buttons(method.reply_markup),
                                           photo=self.file_paths.get(file_id), mid=mid))
            size = PhotoSize(file_id=file_id, file_unique_id=file_id, width=600, height=600)
            return self._msg(chat_id, mid, photo=[size], caption=method.caption, reply_markup=method.reply_markup)
        if isinstance(method, EditMessageText):
            item = self.find(chat_id, method.message_id)
            if item:
                item.text, item.buttons = method.text, _buttons(method.reply_markup)
                self.edited(chat_id, item)
            return self._msg(chat_id, method.message_id, text=method.text, reply_markup=method.reply_markup)
        if isinstance(method, EditMessageReplyMarkup):
            item = self.find(chat_id, method.message_id)
            if item:
                item.buttons = _buttons(method.reply_markup)
                self.edited(chat_id, item)
            return True
        if isinstance(method, DeleteMessage):
            item = self.find(chat_id, method.message_id)
            if item:
                item.deleted = True
            return True
        if isinstance(method, SendInvoice):
            mid = next(self._mid)
            self.add(chat_id, Item("bot", "invoice", f"{method.title}\n{method.description}", mid=mid, extra={
                "payload": method.payload, "currency": method.currency,
                "prices": [(p.label, p.amount) for p in method.prices], "provider_token": method.provider_token,
                "flexible": method.is_flexible}))
            return self._msg(chat_id, mid)
        if isinstance(method, SendDocument):
            mid = next(self._mid)
            doc = method.document
            name = getattr(doc, "filename", None) or "file"
            data = getattr(doc, "data", b"")
            self.add(chat_id, Item("bot", "document", method.caption or "", mid=mid,
                                           extra={"filename": name, "data": data}))
            return self._msg(chat_id, mid, document=Document(file_id=f"doc-{mid}", file_unique_id=f"doc-{mid}",
                                                             file_name=name))
        if isinstance(method, AnswerCallbackQuery):
            if method.text:
                self.toasts.append((0, method.text, bool(method.show_alert)))
            return True
        if isinstance(method, AnswerShippingQuery):
            self.shipping_answers.append(method)
            return True
        if isinstance(method, AnswerPreCheckoutQuery):
            self.pre_checkout_answers.append(method)
            return True
        return True


class Harness:
    """Drive the real dispatcher with fake updates."""

    def __init__(self, settings: Settings | None = None, db: DB | None = None,
                 sheets: SheetsSync | None = None) -> None:
        self.settings = settings or Settings(admin_ids=frozenset({ADMIN_ID}))
        self.db = db or DB(":memory:")
        self.sheets = sheets or SheetsSync(None)
        self.session = FakeSession()
        self.bot = Bot("123456:TEST-TOKEN-NOT-REAL", session=self.session, default=default_props())
        self.dp = build_dispatcher(self.db, self.settings, self.sheets)
        self._ids = itertools.count(1)
        self.frames: list[dict] = []

    # --- users & updates ---------------------------------------------------------
    @staticmethod
    def user(uid: int, first_name: str = "Anna", lang: str = "en", username: str | None = None) -> User:
        return User(id=uid, is_bot=False, first_name=first_name, username=username, language_code=lang)

    def _user_msg(self, u: User, **kw) -> Message:
        return Message(message_id=next(self._ids), date=int(time.time()), chat=Chat(id=u.id, type="private"),
                       from_user=u, **kw)

    async def feed(self, update: Update) -> None:
        await self.dp.feed_update(self.bot, update)

    async def send(self, u: User, text: str) -> None:
        entities = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] if text.startswith("/") else None
        self.session.add(u.id, Item("user", "text", text))
        await self.feed(Update(update_id=next(self._ids), message=self._user_msg(u, text=text, entities=entities)))

    async def send_photo(self, u: User, path: str) -> None:
        file_id = f"user-photo-{next(self._ids)}"
        self.session.file_paths[file_id] = path
        self.session.add(u.id, Item("user", "photo", photo=path))
        size = PhotoSize(file_id=file_id, file_unique_id=file_id, width=600, height=600)
        await self.feed(Update(update_id=next(self._ids), message=self._user_msg(u, photo=[size])))

    def visible(self, chat_id: int) -> list[Item]:
        return [i for i in self.session.chat(chat_id) if not i.deleted]

    def last(self, chat_id: int, who: str = "bot") -> Item:
        return [i for i in self.visible(chat_id) if i.who == who][-1]

    def find_button(self, chat_id: int, label: str) -> tuple[Item, dict]:
        """Newest message having a button whose text equals (or starts with) label."""
        for item in reversed(self.visible(chat_id)):
            for row in item.buttons:
                for btn in row:
                    if btn["text"] == label:
                        return item, btn
            for row in item.buttons:
                for btn in row:
                    if btn["text"].startswith(label):
                        return item, btn
        raise LookupError(f"no button {label!r} in chat {chat_id}")

    async def press(self, u: User, label: str) -> str | None:
        """Tap an inline button. Returns the toast/alert text the bot answered with, if any."""
        item, btn = self.find_button(u.id, label)
        kw: dict = {"caption": item.text} if item.kind == "photo" else {"text": item.text or "."}
        if item.kind == "photo":
            kw["photo"] = [PhotoSize(file_id="x", file_unique_id="x", width=1, height=1)]
        msg = Message(message_id=item.mid, date=int(time.time()), chat=Chat(id=u.id, type="private"),
                      from_user=BOT_USER, **kw)
        before = len(self.session.toasts)
        await self.feed(Update(update_id=next(self._ids), callback_query=CallbackQuery(
            id=str(next(self._ids)), from_user=u, chat_instance="ci", message=msg, data=btn["data"])))
        new = self.session.toasts[before:]
        return new[-1][1] if new else None

    async def pay(self, u: User, country: str = "DE", option: str | None = None, name: str = "Anna Schmidt",
                  phone: str = "+49 151 2345678", city: str = "Berlin", street: str = "Oranienstr. 25",
                  post_code: str = "10999", charge_id: str | None = None, total_override: int | None = None) -> dict:
        """Complete the last invoice like the Telegram payment form does:
        shipping query -> choose option -> pre-checkout -> successful payment."""
        inv = [i for i in self.visible(u.id) if i.kind == "invoice"][-1]
        payload, currency = inv.extra["payload"], inv.extra["currency"]
        items_total = sum(a for _, a in inv.extra["prices"])
        addr = ShippingAddress(country_code=country, state="", city=city, street_line1=street,
                               street_line2="", post_code=post_code)
        await self.feed(Update(update_id=next(self._ids), shipping_query=ShippingQuery(
            id=f"sq{next(self._ids)}", from_user=u, invoice_payload=payload, shipping_address=addr)))
        ship = self.session.shipping_answers[-1]
        result = {"shipping_ok": ship.ok, "options": [(o.id, o.title, sum(p.amount for p in o.prices))
                                                      for o in (ship.shipping_options or [])]}
        if not ship.ok:
            result["error"] = ship.error_message
            return result
        opt = next(o for o in ship.shipping_options if option in (None, o.id))
        total = items_total + sum(p.amount for p in opt.prices) if total_override is None else total_override
        info = OrderInfo(name=name, phone_number=phone, shipping_address=addr)
        await self.feed(Update(update_id=next(self._ids), pre_checkout_query=PreCheckoutQuery(
            id=f"pcq{next(self._ids)}", from_user=u, currency=currency, total_amount=total,
            invoice_payload=payload, shipping_option_id=opt.id, order_info=info)))
        pcq = self.session.pre_checkout_answers[-1]
        result.update(pre_checkout_ok=pcq.ok, total=total, option=opt.id)
        if not pcq.ok:
            result["error"] = pcq.error_message
            return result
        charge = charge_id or f"tgTEST{next(self._ids):06d}"
        sp = SuccessfulPayment(currency=currency, total_amount=total, invoice_payload=payload,
                               shipping_option_id=opt.id, order_info=info, telegram_payment_charge_id=charge,
                               provider_payment_charge_id=f"pi_test_{charge}")
        self.session.add(u.id, Item("user", "payment", f"Paid {total / 100:.2f} {currency} · test card 4242"))
        await self.feed(Update(update_id=next(self._ids), message=self._user_msg(u, successful_payment=sp)))
        result["charge_id"] = charge
        return result

    # --- output ---------------------------------------------------------------------
    def snapshot(self, chat_id: int, title: str, caption: str) -> None:
        self.frames.append({"chat": chat_id, "title": title, "caption": caption,
                            "items": [dict(copy.deepcopy({k: v for k, v in i.__dict__.items() if k != "extra"}),
                                           extra={k: v for k, v in i.extra.items() if k != "data"})
                                      for i in self.visible(chat_id)]})

    def transcript(self, chat_id: int, since: int = 0) -> tuple[str, int]:
        events = self.session.events.get(chat_id, [])
        out = []
        for kind, i in events[since:]:
            if i.who == "user":
                out.append(f"  👤 {i.text or '[photo]'}")
                continue
            head = {"photo": f"[photo {Path(i.photo).name if i.photo else ''}] ", "invoice": "[INVOICE] ",
                    "document": f"[file {i.extra.get('filename')}] "}.get(i.kind, "")
            body = plain(i.text).replace("\n", "\n     ")
            out.append(f"  🤖 {'(edited) ' if kind == 'edit' else ''}{head}{body}")
            n = 0
            for row in i.buttons:
                labels = []
                for btn in row:
                    n += 1
                    labels.append(f"[{btn['text']}]")
                out.append("       " + " ".join(labels))
        return "\n".join(out), len(events)
