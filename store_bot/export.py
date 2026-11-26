"""Order export: CSV file for the admin and optional live sync to Google Sheets.

Google Sheets sync posts each order row to a Google Apps Script web app (apps_script.gs),
which upserts it by order id. No Google Cloud project or service account is needed.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from . import orders as orders_mod
from .db import DB

log = logging.getLogger(__name__)

CSV_FIELDS = ["order_id", "created", "paid", "status", "customer", "phone", "email", "country", "address",
              "items", "subtotal", "shipping", "shipping_option", "total", "currency", "telegram_user_id",
              "charge_id"]


def _ts(value: int | None) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if value else ""


def order_row(order: dict) -> dict:
    items = "; ".join(f"{i['name']}{' (' + i['size'] + ')' if i['size'] else ''} x{i['qty']}"
                      for i in order["items"])
    return {
        "order_id": order["id"], "created": _ts(order["created_at"]), "paid": _ts(order["paid_at"]),
        "status": order["status"], "customer": order["customer_name"] or "", "phone": order["phone"] or "",
        "email": order["email"] or "", "country": order["country"] or "", "address": order["address"] or "",
        "items": items, "subtotal": f"{order['subtotal_cents'] / 100:.2f}",
        "shipping": f"{order['shipping_cents'] / 100:.2f}", "shipping_option": order["shipping_option"] or "",
        "total": f"{order['total_cents'] / 100:.2f}", "currency": order["currency"],
        "telegram_user_id": order["user_id"], "charge_id": order["charge_id"] or "",
    }


def orders_csv(db: DB, include_unpaid: bool = False) -> bytes:
    where = "" if include_unpaid else "WHERE paid_at IS NOT NULL"
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for r in db.all(f"SELECT id FROM orders {where} ORDER BY id"):
        writer.writerow(order_row(orders_mod.get_order(db, r["id"])))
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens umlauts/cyrillic correctly


Poster = Callable[[str, dict], Awaitable[None]]


async def _aiohttp_post(url: str, body: dict) -> None:
    import aiohttp

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
        async with s.post(url, json=body) as resp:
            text = await resp.text()
            if resp.status != 200 or '"ok":true' not in text.replace(" ", ""):
                raise RuntimeError(f"sheets webhook answered {resp.status}: {text[:200]}")


class SheetsSync:
    """Fire-and-forget push of order rows; the bot never waits for Google. Disabled without a URL."""

    def __init__(self, url: str | None, secret: str | None = None, poster: Poster | None = None,
                 retries: int = 3) -> None:
        self.url, self.secret, self.retries = url, secret, retries
        self.poster = poster or _aiohttp_post
        self._tasks: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    async def push(self, row: dict) -> bool:
        if not self.enabled:
            return False
        body = {"secret": self.secret or "", "row": row}
        for attempt in range(1, self.retries + 1):
            try:
                await self.poster(self.url, body)
                return True
            except Exception as exc:  # network, quota, script error
                log.warning("Sheets push failed (try %s/%s): %s", attempt, self.retries, exc)
                await asyncio.sleep(min(2 ** attempt, 10) if attempt < self.retries else 0)
        return False

    def schedule(self, order: dict) -> None:
        if not self.enabled:
            return
        task = asyncio.create_task(self.push(order_row(order)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
