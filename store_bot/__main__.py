"""Entry point.

    python -m store_bot            # real bot if BOT_TOKEN is set, otherwise the offline console
    python -m store_bot --demo     # scripted offline demo, prints the whole dialog
    python -m store_bot --console  # interactive offline emulator
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="store_bot")
    parser.add_argument("--demo", action="store_true", help="run the scripted offline demo")
    parser.add_argument("--console", action="store_true", help="interactive offline emulator")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()

    from . import demo

    if args.demo:
        logging.getLogger("aiogram.event").setLevel(logging.WARNING)
        asyncio.run(demo.scripted())
    elif args.console or settings.test_mode:
        logging.getLogger("aiogram.event").setLevel(logging.WARNING)
        if not args.console:
            print("BOT_TOKEN is not set (or TEST_MODE=1): starting the offline emulator.\n")
        if args.console or sys.stdin.isatty():
            asyncio.run(demo.console())
        else:
            asyncio.run(demo.scripted())
    else:
        from .bot import run_polling

        asyncio.run(run_polling(settings))


if __name__ == "__main__":
    main()
