# ============ ОСНОВНЫЕ НАСТРОЙКИ ============
# Получить у @BotFather
BOT_TOKEN = "9201510613:AAFZmGswiKvLS2BBriyBfN2gpHEaSmrVt2c"

# Ваш Telegram ID (узнать у @userinfobot). Можно несколько: [111, 222]
ADMIN_IDS = [1366711672]

# ============ ОФОРМЛЕНИЕ ============
SHOP_NAME = "Playerok Shop"
SHOP_DESCRIPTION = "Быстрая выдача игровых товаров 24/7"
SUPPORT_CONTACT = "@your_support"  # показывается покупателю
WELCOME_MESSAGE = (
    "👋 Добро пожаловать в <b>Playerok Shop</b>!\n\n"
    "🛒 /catalog — каталог товаров\n"
    "📦 /my_orders — мои покупки\n"
    f"💬 Поддержка: {SUPPORT_CONTACT}"
)

# ============ ОПЛАТА ============
# Валюта: XTR = Telegram Stars (рекомендуется для цифровых товаров)
CURRENCY = "XTR"

# ============ СЛУЖЕБНОЕ ============
DB_PATH = "shop.db"           # файл базы данных
MAX_ORDERS_HISTORY = 10       # сколько последних покупок показывать пользователю