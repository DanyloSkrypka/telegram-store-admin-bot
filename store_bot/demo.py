"""Offline demo: scripted scenario and an interactive console, both on the built-in Telegram emulator.

    python -m store_bot --demo      # scripted: customer buys, owner ships, owner adds a product
    python -m store_bot --console   # you are the customer; type a button number, text, or /pay
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .db import ASSETS
from .emulator import ADMIN_ID, Harness, plain

ROOT = Path(__file__).resolve().parent.parent


async def scripted(frames_out: Path | None = None, quiet: bool = False) -> Harness:
    h = Harness()
    anna, owner, lukas = h.user(42, "Anna"), h.user(ADMIN_ID, "Owner"), h.user(43, "Lukas", lang="de")
    C, A = "Customer · Anna", "Shop owner"
    marks = {42: 0, ADMIN_ID: 0, 43: 0}

    def out(chat: int, header: str) -> None:
        if quiet:
            return
        text, marks[chat] = h.transcript(chat, marks[chat])
        if text:
            print(f"\n=== {header} ===\n{text}")

    async def step(u, action: str, caption: str, title: str) -> None:
        if action.startswith("tap:"):
            toast = await h.press(u, action[4:])
            if toast and not quiet:
                print(f"  💬 toast: {toast}")
        else:
            await h.send(u, action)
        h.snapshot(u.id, title, caption)

    await step(anna, "/start", "/start", C)
    await step(anna, "tap:🛍 Catalog", "Catalog", C)
    await step(anna, "tap:T-shirts", "Category", C)
    await step(anna, "tap:Classic Logo Tee", "Product card with photo", C)
    await step(anna, "tap:M", "Size M → added to cart", C)
    await step(anna, "tap:⬅️ Back", "Back", C)
    await step(anna, "tap:Heavyweight Box Tee", "Another product", C)
    await step(anna, "tap:L", "Size L → added", C)
    await step(anna, "tap:🛒 Cart", "Cart", C)
    await step(anna, "tap:➕", "+1 in the cart", C)
    await step(anna, "tap:✅ Checkout", "Checkout → Telegram invoice", C)
    out(42, "Customer chat")
    res = await h.pay(anna, country="DE")
    h.snapshot(42, C, f"Paid {res['total'] / 100:.2f} € with Stripe TEST card")
    if not quiet:
        print(f"\n  💳 payment form: shipping options {res['options']} → pre-checkout ok={res['pre_checkout_ok']}, "
              f"charged {res['total'] / 100:.2f} EUR (test)")
    out(42, "Customer chat")
    h.snapshot(ADMIN_ID, A, "Owner gets the paid order instantly")
    out(ADMIN_ID, "Owner chat")
    await step(owner, "tap:📦 Mark packed", "Owner: packed", A)
    await step(owner, "tap:🚚 Mark shipped", "Owner: shipped", A)
    h.snapshot(42, C, "Customer is notified automatically")
    out(42, "Customer chat")
    await step(owner, "/admin", "Admin panel", A)
    await step(owner, "tap:➕ Add product", "Add product wizard", A)
    await step(owner, "tap:Accessories", "Category", A)
    for text in ["Beanie | Mütze | Шапка", "Rib knit, warm, one size. | Rippstrick, warm, Einheitsgröße. | "
                 "Резинка, тёплая, один размер.", "19.90", "15", "-"]:
        await step(owner, text, "Wizard step", A)
    await h.send_photo(owner, str(ASSETS / "new_beanie.png"))
    h.snapshot(ADMIN_ID, A, "Product is live")
    await step(owner, "tap:🏠 Admin", "Admin panel", A)
    await step(owner, "tap:📤 Export CSV", "CSV export", A)
    out(ADMIN_ID, "Owner chat")
    await step(lukas, "/start", "German user: auto language", "Customer · Lukas (DE)")
    await step(lukas, "tap:🛍 Katalog", "Katalog", "Customer · Lukas (DE)")
    await step(lukas, "tap:Accessoires", "New product is in the shop", "Customer · Lukas (DE)")
    await step(lukas, "tap:Mütze", "Product card in German", "Customer · Lukas (DE)")
    out(43, "Customer chat (German)")
    await h.sheets.drain()
    if frames_out:
        frames_out.parent.mkdir(parents=True, exist_ok=True)
        frames_out.write_text(json.dumps(h.frames, ensure_ascii=False, indent=1))
    if not quiet:
        csv = [i for i in h.session.chat(ADMIN_ID) if i.kind == "document"][-1].extra["data"].decode("utf-8-sig")
        print("\n=== orders.csv ===\n" + csv.strip())
    return h


HELP = ("Type a button number to tap it, any text to send it, /pay [COUNTRY] to complete the invoice "
        "(test card), /owner or /me to switch between shop owner and customer, /quit to exit.")


async def console() -> None:
    h = Harness()
    me, owner = h.user(42, "You"), h.user(ADMIN_ID, "Owner")
    current = me
    seen = {42: 0, ADMIN_ID: 0}
    print(f"KIEZ Supply — offline Telegram emulator. {HELP}\n")
    await h.send(me, "/start")
    while True:
        for chat, title in ((42, "customer"), (ADMIN_ID, "owner")):
            text, seen[chat] = h.transcript(chat, seen[chat])
            if text.strip():
                print(f"--- {title} chat ---\n{text}")
        buttons = []
        try:
            item = next(i for i in reversed(h.visible(current.id)) if i.buttons)
            buttons = [b for row in item.buttons for b in row]
            print("  " + "  ".join(f"{n}) {b['text']}" for n, b in enumerate(buttons, 1)))
        except StopIteration:
            pass
        try:
            line = (await asyncio.to_thread(input, f"[{'owner' if current is owner else 'you'}] > ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in {"/quit", "/exit", "q"}:
            break
        if line == "/owner":
            current = owner
            if not h.session.chat(ADMIN_ID):
                await h.send(owner, "/admin")
        elif line == "/me":
            current = me
        elif line.startswith("/pay"):
            country = (line.split()[1:] or ["DE"])[0].upper()
            try:
                res = await h.pay(current, country=country)
                print(f"  💳 {res}")
            except IndexError:
                print("  no invoice yet — add items and tap Checkout first")
        elif line.isdigit() and 1 <= int(line) <= len(buttons):
            toast = await h.press(current, buttons[int(line) - 1]["text"])
            if toast:
                print(f"  💬 {plain(toast)}")
        elif line:
            await h.send(current, line)
