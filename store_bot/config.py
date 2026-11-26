"""Settings from environment variables (.env is loaded if python-dotenv is installed)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # optional
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _ids(raw: str | None) -> frozenset[int]:
    out = set()
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return frozenset(out)


def _flag(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    bot_token: str | None = None
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    provider_token: str | None = None      # Telegram Payments provider token (Stripe TEST)
    currency: str = "EUR"
    db_path: str = "data/store.db"
    shop_name: str = "KIEZ Supply"
    default_lang: str = "en"
    payments_test: bool = True             # show the Stripe test card hint
    free_shipping_de_cents: int = 8000     # free standard shipping in DE from this subtotal
    sheets_webhook_url: str | None = None  # optional Google Apps Script web app
    sheets_secret: str | None = None

    @property
    def test_mode(self) -> bool:
        """No real token -> run against the built-in Telegram emulator."""
        return not self.bot_token or _flag(os.getenv("TEST_MODE"))

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids


def load_settings(env: dict | None = None) -> Settings:
    e = os.environ if env is None else env
    return Settings(
        bot_token=(e.get("BOT_TOKEN") or "").strip() or None,
        admin_ids=_ids(e.get("ADMIN_IDS")),
        provider_token=(e.get("PAYMENT_PROVIDER_TOKEN") or "").strip() or None,
        currency=(e.get("CURRENCY") or "EUR").upper(),
        db_path=e.get("DB_PATH") or "data/store.db",
        shop_name=e.get("SHOP_NAME") or "KIEZ Supply",
        default_lang=(e.get("DEFAULT_LANG") or "en").lower(),
        payments_test=_flag(e.get("PAYMENTS_TEST"), True),
        free_shipping_de_cents=int(e.get("FREE_SHIPPING_DE_CENTS") or 8000),
        sheets_webhook_url=(e.get("SHEETS_WEBHOOK_URL") or "").strip() or None,
        sheets_secret=(e.get("SHEETS_SECRET") or "").strip() or None,
    )
