"""Dispatcher wiring and the real long-polling entry point."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, TelegramObject

from .config import Settings
from .db import DB
from .export import SheetsSync
from .handlers import admin, shop

log = logging.getLogger(__name__)


def default_props() -> DefaultBotProperties:
    return DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)


class UserMiddleware(BaseMiddleware):
    """Registers the user on first contact and injects `lang` into every handler."""

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]],
                       event: TelegramObject, data: dict) -> Any:
        user = data.get("event_from_user")
        settings: Settings = data["settings"]
        if user and not user.is_bot:
            data["lang"] = data["db"].ensure_user(user.id, user.first_name, user.username,
                                                  user.language_code, settings.default_lang)
        else:
            data["lang"] = settings.default_lang
        return await handler(event, data)


def build_dispatcher(db: DB, settings: Settings, sheets: SheetsSync) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())  # use RedisStorage in production for multi-instance
    dp["db"], dp["settings"], dp["sheets"] = db, settings, sheets
    dp.update.outer_middleware(UserMiddleware())
    # admin first (its wizard states must win), generic fallback last
    dp.include_routers(admin.get_router(), shop.get_router(), shop.get_fallback_router())

    @dp.errors()
    async def on_error(event) -> bool:
        log.exception("update failed: %s", event.exception)
        return True

    return dp


async def run_polling(settings: Settings) -> None:
    db = DB(settings.db_path)
    sheets = SheetsSync(settings.sheets_webhook_url, settings.sheets_secret)
    bot = Bot(settings.bot_token, default=default_props())
    dp = build_dispatcher(db, settings, sheets)
    await bot.set_my_commands([BotCommand(command="start", description="Shop / Shop / Магазин"),
                               BotCommand(command="language", description="Language / Sprache / Язык")])
    if not settings.provider_token:
        log.warning("PAYMENT_PROVIDER_TOKEN is empty: checkout will tell customers payments are not configured")
    if not settings.admin_ids:
        log.warning("ADMIN_IDS is empty: nobody gets order alerts or /admin")
    log.info("bot started, Sheets sync %s", "on" if sheets.enabled else "off")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await sheets.drain()
        await bot.session.close()
