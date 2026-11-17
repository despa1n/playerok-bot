import asyncio
import logging
import csv
import io
import os
from datetime import datetime

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery, LabeledPrice,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile,
)

# ================== КОНФИГ ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_СЮДА_ТОКЕН_ЕСЛИ_ЛОКАЛЬНО")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x]
DB_PATH = "shop.db"

logging.basicConfig(level=logging.INFO)
router = Router()

# ================== БАЗА ДАННЫХ ==================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            price INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            sold INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            product_id INTEGER NOT NULL,
            product_title TEXT NOT NULL,
            stock_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            amount INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        await db.commit()

async def get_active_products():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, title, description, price FROM products WHERE active=1 ORDER BY id") as cur:
            return await cur.fetchall()

async def get_product(pid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, title, description, price, active FROM products WHERE id=?", (pid,)) as cur:
            return await cur.fetchone()

async def count_stock(pid: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM stock WHERE product_id=? AND sold=0", (pid,)) as cur:
            return (await cur.fetchone())[0]

async def issue_product(pid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute("SELECT id, content FROM stock WHERE product_id=? AND sold=0 LIMIT 1", (pid,)) as cur:
                row = await cur.fetchone()
            if not row:
                await db.rollback()
                return None
            stock_id, content = row
            await db.execute("UPDATE stock SET sold=1 WHERE id=?", (stock_id,))
            await db.commit()
            return stock_id, content
        except Exception:
            await db.rollback()
            raise

async def save_order(user_id, username, pid, title, stock_id, content, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO orders (user_id, username, product_id, product_title, stock_id, content, amount, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, username, pid, title, stock_id, content, amount, datetime.utcnow().isoformat())
        )
        await db.commit()

# ================== ХЕНДЛЕРЫ ==================
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("👋 Добро пожаловать в магазин!\n\n🛒 /catalog — каталог\n📦 /my_orders — покупки\n💬 Поддержка: @support")
@router.message(Command("catalog"))
async def cmd_catalog(message: Message):
    products = await get_active_products()
    if not products:
        await message.answer("😔 Каталог пуст.")
        return
    for pid, title, desc, price in products:
        left = await count_stock(pid)
        if left == 0: continue
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"💳 Купить за {price} ⭐ (в наличии: {left})", callback_data=f"buy:{pid}")]])
        await message.answer(f"<b>{title}</b>\n\n{desc}\n\n💰 Цена: <b>{price}</b> ⭐", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, bot: Bot):
    pid = int(call.data.split(":")[1])
    product = await get_product(pid)
    if not product or not product[4] or await count_stock(pid) <= 0:
        await call.answer("Товар недоступен", show_alert=True)
        return
    _, title, desc, price, _ = product
    await bot.send_invoice(chat_id=call.from_user.id, title=title[:32], description=desc[:255], payload=f"product:{pid}", provider_token="", currency="XTR", prices=[LabeledPrice(label=title[:32], amount=price)])
    await call.answer()

@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    try:
        pid = int(query.invoice_payload.split(":")[1])
    except:
        await query.answer(ok=False, error_message="Ошибка")
        return
    if await count_stock(pid) <= 0:
        await query.answer(ok=False, error_message="Товар закончился")
        return
    await query.answer(ok=True)

@router.message(F.successful_payment)
async def on_payment(message: Message, bot: Bot):
    payment = message.successful_payment
    pid = int(payment.invoice_payload.split(":")[1])
    product = await get_product(pid)
    title = product[1] if product else "Товар"
    issue = await issue_product(pid)
    if not issue:
        await message.answer("⚠️ Товар закончился. Напишите в поддержку.")
        return
    stock_id, content = issue
    await save_order(message.from_user.id, message.from_user.username, pid, title, stock_id, content, payment.total_amount)
    await message.answer(f"✅ <b>Оплата получена!</b>\n\n📦 <b>{title}</b>\n\n<code>{content}</code>\n\n💬 Поддержка: @support\n📄 Чек: /my_orders", parse_mode="HTML")

@router.message(Command("my_orders"))
async def cmd_my_orders(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT product_title, amount, created_at, content FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (message.from_user.id,)) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("У вас нет покупок.")
        return
    text = "📦 <b>Ваши покупки:</b>\n\n"
    for t, a, c, cont in rows:
        text += f"• <b>{t}</b> — {a} ⭐\n  <code>{cont}</code>\n  <i>{c[:16]}</i>\n\n"
    await message.answer(text, parse_mode="HTML")

# ================== АДМИНКА ==================
def is_admin(uid: int) -> bool: return uid in ADMIN_IDS

class AddProduct(StatesGroup):
    title = State()
    description = State()
    price = State()

class AddStock(StatesGroup):
    pid = State()
    items = State()

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer("🛠 <b>Админка</b>\n\n📋 /products\n➕ /add_product\n📥 /add_stock\n📊 /stats", parse_mode="HTML")

@router.message(Command("add_product"))
async def add_product_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AddProduct.title)
    await message.answer("📝 Название товара (или /cancel):")

@router.message(AddProduct.title)
async def add_p_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddProduct.description)
    await message.answer("📝 Описание:")
@router.message(AddProduct.description)
async def add_p_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddProduct.price)
    await message.answer("💰 Цена в звёздах (число):")

@router.message(AddProduct.price)
async def add_p_price(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Нужно число:")
        return
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO products (title, description, price, created_at) VALUES (?,?,?,?)", (data["title"], data["description"], int(message.text), datetime.utcnow().isoformat()))
        await db.commit()
        pid = cur.lastrowid
    await state.clear()
    await message.answer(f"✅ Товар создан! ID: <code>{pid}</code>\n\nЗагрузите склад: /add_stock {pid}", parse_mode="HTML")

@router.message(Command("add_stock"))
async def add_stock_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) == 2 and parts[1].isdigit():
        await state.update_data(pid=int(parts[1]))
        await state.set_state(AddStock.items)
        await message.answer("📥 Отправьте позиции (каждая с новой строки):")
        return
    await state.set_state(AddStock.pid)
    await message.answer("Введите ID товара:")

@router.message(AddStock.pid)
async def add_s_pid(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ ID — число:")
        return
    await state.update_data(pid=int(message.text))
    await state.set_state(AddStock.items)
    await message.answer("📥 Отправьте позиции (каждая с новой строки):")

@router.message(AddStock.items)
async def add_s_items(message: Message, state: FSMContext):
    data = await state.get_data()
    lines = [ln.strip() for ln in message.text.split("\n") if ln.strip()]
    if not lines:
        await message.answer("❌ Пусто. /cancel")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany("INSERT INTO stock (product_id, content) VALUES (?,?)", [(data["pid"], ln) for ln in lines])
        await db.commit()
    await message.answer(f"✅ Добавлено: {len(lines)} позиций.\n📦 На складе: {await count_stock(data['pid'])}")

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")

@router.message(Command("products"))
async def cmd_products(message: Message):
    if not is_admin(message.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, title, price, active FROM products ORDER BY id") as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("Товаров нет.")
        return
    text = "<b>Товары:</b>\n"
    for pid, title, price, active in rows:
        text += f"{'🟢' if active else '🔴'} <code>#{pid}</code> <b>{title}</b> — {price} ⭐ (склад: {await count_stock(pid)})\n"
    await message.answer(text, parse_mode="HTML")

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM orders") as cur:
            orders, stars = await cur.fetchone()
    await message.answer(f"📊 <b>Статистика</b>\n\n💰 Заказов: <b>{orders}</b>\n⭐ Оборот: <b>{stars}</b> ⭐", parse_mode="HTML")

# ================== ЗАПУСК ==================
async def main():
    await init_db()
    clean_token = BOT_TOKEN.strip().strip('"').strip("'")
    bot = Bot(token=clean_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logging.info("Bot запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
