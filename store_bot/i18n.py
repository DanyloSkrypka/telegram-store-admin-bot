"""Customer-facing texts in English, German and Russian.

Every key must exist in all three languages (checked by tests/test_i18n.py).
"""
from __future__ import annotations

LANGS = ("en", "de", "ru")
LANG_NAMES = {"en": "🇬🇧 English", "de": "🇩🇪 Deutsch", "ru": "🇷🇺 Русский"}

TEXTS: dict[str, dict[str, str]] = {
    "welcome": {
        "en": "👋 Hi, {name}! Welcome to <b>{shop}</b>.\nStreetwear from Berlin — order right here in the chat.",
        "de": "👋 Hallo, {name}! Willkommen bei <b>{shop}</b>.\nStreetwear aus Berlin — bestell direkt hier im Chat.",
        "ru": "👋 Привет, {name}! Это <b>{shop}</b>.\nСтритвир из Берлина — заказ прямо в чате.",
    },
    "menu": {"en": "Main menu", "de": "Hauptmenü", "ru": "Главное меню"},
    "btn_catalog": {"en": "🛍 Catalog", "de": "🛍 Katalog", "ru": "🛍 Каталог"},
    "btn_cart": {"en": "🛒 Cart ({n})", "de": "🛒 Warenkorb ({n})", "ru": "🛒 Корзина ({n})"},
    "btn_orders": {"en": "📦 My orders", "de": "📦 Meine Bestellungen", "ru": "📦 Мои заказы"},
    "btn_lang": {"en": "🌐 Language", "de": "🌐 Sprache", "ru": "🌐 Язык"},
    "btn_back": {"en": "⬅️ Back", "de": "⬅️ Zurück", "ru": "⬅️ Назад"},
    "btn_menu": {"en": "🏠 Menu", "de": "🏠 Menü", "ru": "🏠 Меню"},
    "choose_lang": {"en": "Choose your language:", "de": "Sprache wählen:", "ru": "Выбери язык:"},
    "lang_set": {"en": "Language: English", "de": "Sprache: Deutsch", "ru": "Язык: русский"},
    "categories": {"en": "Choose a category:", "de": "Kategorie wählen:", "ru": "Выбери категорию:"},
    "category_empty": {"en": "Nothing here yet.", "de": "Hier ist noch nichts.", "ru": "Здесь пока пусто."},
    "sold_out": {"en": "sold out", "de": "ausverkauft", "ru": "нет в наличии"},
    "in_stock": {"en": "In stock: {n}", "de": "Auf Lager: {n}", "ru": "В наличии: {n}"},
    "pick_size": {"en": "Pick a size to add to cart:", "de": "Größe wählen und in den Warenkorb:",
                  "ru": "Выбери размер — добавлю в корзину:"},
    "btn_add": {"en": "➕ Add to cart", "de": "➕ In den Warenkorb", "ru": "➕ В корзину"},
    "added": {"en": "Added: {item}", "de": "Hinzugefügt: {item}", "ru": "Добавлено: {item}"},
    "err_out_of_stock": {"en": "Sorry, not enough in stock.", "de": "Leider nicht genug auf Lager.",
                         "ru": "Увы, столько нет в наличии."},
    "err_unavailable": {"en": "This product is no longer available.", "de": "Dieses Produkt ist nicht mehr verfügbar.",
                        "ru": "Этот товар больше недоступен."},
    "err_bad_size": {"en": "Please choose a size.", "de": "Bitte eine Größe wählen.", "ru": "Выбери размер."},
    "cart_title": {"en": "🛒 <b>Your cart</b>", "de": "🛒 <b>Dein Warenkorb</b>", "ru": "🛒 <b>Твоя корзина</b>"},
    "cart_empty": {"en": "Your cart is empty.", "de": "Dein Warenkorb ist leer.", "ru": "Корзина пуста."},
    "subtotal": {"en": "Subtotal: <b>{sum}</b>", "de": "Zwischensumme: <b>{sum}</b>", "ru": "Сумма: <b>{sum}</b>"},
    "shipping_note": {"en": "Shipping is calculated at checkout (free in Germany from {free}).",
                      "de": "Versand wird beim Bezahlen berechnet (in Deutschland ab {free} gratis).",
                      "ru": "Доставка считается при оплате (по Германии бесплатно от {free})."},
    "btn_checkout": {"en": "✅ Checkout", "de": "✅ Zur Kasse", "ru": "✅ Оформить"},
    "btn_clear": {"en": "🗑 Clear", "de": "🗑 Leeren", "ru": "🗑 Очистить"},
    "cart_cleared": {"en": "Cart cleared", "de": "Warenkorb geleert", "ru": "Корзина очищена"},
    "invoice_title": {"en": "{shop} — order #{id}", "de": "{shop} — Bestellung #{id}", "ru": "{shop} — заказ #{id}"},
    "invoice_desc": {"en": "{items}. Delivery address and shipping method on the next step.",
                     "de": "{items}. Lieferadresse und Versandart im nächsten Schritt.",
                     "ru": "{items}. Адрес и способ доставки — на следующем шаге."},
    "checkout_hint": {"en": "Order <b>#{id}</b> created. Tap <b>Pay</b> below — Telegram will ask for your address and shipping method.",
                      "de": "Bestellung <b>#{id}</b> erstellt. Tippe unten auf <b>Bezahlen</b> — Telegram fragt nach Adresse und Versandart.",
                      "ru": "Заказ <b>#{id}</b> создан. Нажми <b>Оплатить</b> ниже — Telegram спросит адрес и доставку."},
    "test_card": {"en": "🧪 Test mode: card 4242 4242 4242 4242, any future date, any CVC. No real money.",
                  "de": "🧪 Testmodus: Karte 4242 4242 4242 4242, beliebiges künftiges Datum, beliebiger CVC. Kein echtes Geld.",
                  "ru": "🧪 Тестовый режим: карта 4242 4242 4242 4242, любая будущая дата, любой CVC. Деньги не списываются."},
    "pay_not_configured": {"en": "Payments are not configured yet. Please contact the shop.",
                           "de": "Zahlungen sind noch nicht eingerichtet. Bitte kontaktiere den Shop.",
                           "ru": "Оплата пока не настроена. Напиши магазину."},
    "ship_de_std": {"en": "DHL Standard (2–3 days)", "de": "DHL Standard (2–3 Tage)", "ru": "DHL Стандарт (2–3 дня)"},
    "ship_de_express": {"en": "DHL Express (next day)", "de": "DHL Express (nächster Tag)", "ru": "DHL Экспресс (на след. день)"},
    "ship_eu_std": {"en": "EU Standard (4–7 days)", "de": "EU Standard (4–7 Tage)", "ru": "Доставка по ЕС (4–7 дней)"},
    "ship_world": {"en": "Worldwide (7–14 days)", "de": "Weltweit (7–14 Tage)", "ru": "По миру (7–14 дней)"},
    "err_order_changed": {"en": "This order has changed or is outdated. Please check out again.",
                          "de": "Diese Bestellung hat sich geändert oder ist veraltet. Bitte erneut zur Kasse.",
                          "ru": "Заказ изменился или устарел. Оформи заново."},
    "err_stock_changed": {"en": "Some items just sold out. Please check your cart.",
                          "de": "Einige Artikel sind gerade ausverkauft. Bitte prüfe den Warenkorb.",
                          "ru": "Часть товаров только что закончилась. Проверь корзину."},
    "err_no_shipping": {"en": "We can't ship to this address.", "de": "An diese Adresse können wir nicht liefern.",
                        "ru": "На этот адрес доставить не можем."},
    "paid_thanks": {"en": "🎉 Thank you! Order <b>#{id}</b> is paid: {sum}.\nWe'll message you when it ships.",
                    "de": "🎉 Danke! Bestellung <b>#{id}</b> ist bezahlt: {sum}.\nWir melden uns, sobald sie verschickt ist.",
                    "ru": "🎉 Спасибо! Заказ <b>#{id}</b> оплачен: {sum}.\nНапишем, когда отправим."},
    "orders_title": {"en": "📦 <b>Your orders</b>", "de": "📦 <b>Deine Bestellungen</b>", "ru": "📦 <b>Твои заказы</b>"},
    "orders_empty": {"en": "No orders yet.", "de": "Noch keine Bestellungen.", "ru": "Заказов пока нет."},
    "status_update": {"en": "🔔 Order <b>#{id}</b>: {status}", "de": "🔔 Bestellung <b>#{id}</b>: {status}",
                      "ru": "🔔 Заказ <b>#{id}</b>: {status}"},
    "status_new": {"en": "awaiting payment", "de": "wartet auf Zahlung", "ru": "ждёт оплаты"},
    "status_paid": {"en": "paid ✅", "de": "bezahlt ✅", "ru": "оплачен ✅"},
    "status_packed": {"en": "packed 📦", "de": "verpackt 📦", "ru": "собран 📦"},
    "status_shipped": {"en": "shipped 🚚", "de": "versendet 🚚", "ru": "отправлен 🚚"},
    "status_delivered": {"en": "delivered 🏁", "de": "zugestellt 🏁", "ru": "доставлен 🏁"},
    "status_cancelled": {"en": "cancelled ❌", "de": "storniert ❌", "ru": "отменён ❌"},
    "unknown": {"en": "Use the buttons below 👇", "de": "Nutze die Buttons unten 👇", "ru": "Пользуйся кнопками ниже 👇"},
}


def detect_lang(language_code: str | None, default: str = "en") -> str:
    code = (language_code or "").lower().split("-")[0]
    if code == "de":
        return "de"
    if code in {"ru", "uk", "be", "kk"}:
        return "ru"
    if code == "en":
        return "en"
    return default if default in LANGS else "en"


def t(lang: str, key: str, **kw) -> str:
    entry = TEXTS[key]
    text = entry.get(lang) or entry["en"]
    return text.format(**kw) if kw else text


def money(cents: int, lang: str = "en", currency: str = "EUR") -> str:
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency, currency + " ")
    s = f"{cents / 100:,.2f}"
    if lang == "en":
        return f"{sym}{s}"
    s = s.replace(",", " ").replace(".", ",")
    return f"{s} {sym}"
