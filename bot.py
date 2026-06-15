import asyncio
import logging
import sqlite3
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHAT_ID = int(os.getenv("CHAT_ID"))
THREAD_ID = os.getenv("THREAD_ID")
if THREAD_ID:
    THREAD_ID = int(THREAD_ID)
else:
    THREAD_ID = None
DB_NAME = "payout.db"

# ---------- ID премиум-эмодзи ----------
EMOJI_MONEY = "5409048419211682843"      # 💵
EMOJI_CHECK = "5206607081334906820"      # ✅
EMOJI_CROSS = "5240241223632954241"      # ❌
EMOJI_SHOP = "5377660214096974712"       # 🛍
EMOJI_WARNING = "5440660757194744323"    # ‼️
EMOJI_PENCIL = "5197269100878907942"     # ✍️
EMOJI_CAMERA = "5902449142575141204"     # 📸
EMOJI_DIAMOND = "5427168083074628963"    # 💎
EMOJI_FIRE = "6039802097916974085"       # 🔥
EMOJI_MONEY2 = "5375296873982604963"     # 💰
EMOJI_HANDSHAKE = "5395732581780040886"  # 🤝

# ---------- База данных ----------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            deal_number TEXT,
            nft_link TEXT,
            ton_wallet TEXT,
            photos TEXT,
            status TEXT,
            created_at TEXT,
            processed_at TEXT,
            amount TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_request(user_id, username, deal_number, nft_link, ton_wallet, photos):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    photos_str = ','.join(photos)
    cur.execute('''
        INSERT INTO requests (user_id, username, deal_number, nft_link, ton_wallet, photos, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, username, deal_number, nft_link, ton_wallet, photos_str, 'pending', datetime.now().isoformat()))
    req_id = cur.lastrowid
    conn.commit()
    conn.close()
    return req_id

def get_request(req_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM requests WHERE id = ?", (req_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def update_request(req_id, status, amount=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        UPDATE requests SET status = ?, processed_at = ?, amount = ? WHERE id = ?
    ''', (status, datetime.now().isoformat(), amount, req_id))
    conn.commit()
    conn.close()

# ---------- FSM состояния ----------
class PayoutFSM(StatesGroup):
    waiting_deal_number = State()
    waiting_nft_link = State()
    waiting_photos = State()
    waiting_wallet = State()
    waiting_confirm = State()

class AdminFSM(StatesGroup):
    waiting_amount = State()

# ---------- Клавиатуры ----------
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Создать выплату",
            callback_data="create_payout",
            icon_custom_emoji_id=EMOJI_MONEY
        )]
    ])

def admin_buttons(req_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"approve_{req_id}",
                icon_custom_emoji_id=EMOJI_CHECK
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"reject_{req_id}",
                icon_custom_emoji_id=EMOJI_CROSS
            )
        ]
    ])

def cancel_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Отмена",
            callback_data="cancel_request",
            icon_custom_emoji_id=EMOJI_CROSS
        )]
    ])

# ---------- Бот ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"<tg-emoji emoji-id='{EMOJI_SHOP}'>🛍</tg-emoji> <b>Бот для выплат по сделкам</b>\n\n"
        f"<blockquote><tg-emoji emoji-id='{EMOJI_WARNING}'>‼️</tg-emoji> Нажмите кнопку ниже, чтобы создать заявку на выплату.</blockquote>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@dp.message(Command("chatid"))
async def chatid_cmd(message: Message):
    await message.answer(f"ID этого чата: `{message.chat.id}`", parse_mode="Markdown")

@dp.message(Command("threadid"))
async def threadid_cmd(message: Message):
    thread_id = message.message_thread_id
    if thread_id:
        await message.answer(f"ID этой темы: `{thread_id}`", parse_mode="Markdown")
    else:
        await message.answer("Это сообщение не в топике. Убедитесь, что топики включены в группе и вы пишете в нужной теме.")

@dp.message(Command("check_chat"))
async def check_chat_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Только для администратора.")
        return
    try:
        chat = await bot.get_chat(CHAT_ID)
        await message.answer(
            f"✅ Чат с ID `{CHAT_ID}` найден!\n"
            f"Название: {chat.title}\n"
            f"Тип: {chat.type}\n"
            f"Бот в чате? {'Да' if chat.permissions else 'Неизвестно'}\n"
            f"Попробую отправить тестовое сообщение...",
            parse_mode="Markdown"
        )
        if THREAD_ID:
            await bot.send_message(CHAT_ID, "🧪 Тестовое сообщение от бота для проверки связи.", message_thread_id=THREAD_ID)
            await message.answer(f"✅ Тестовое сообщение отправлено в тему с ID {THREAD_ID}.")
        else:
            await bot.send_message(CHAT_ID, "🧪 Тестовое сообщение от бота для проверки связи.")
            await message.answer(f"✅ Тестовое сообщение отправлено в чат {CHAT_ID}.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при проверке чата: {e}")

@dp.callback_query(lambda c: c.data == "create_payout")
async def create_payout(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer(
        f"<tg-emoji emoji-id='{EMOJI_PENCIL}'>✍️</tg-emoji> <b>Введите номер сделки:</b>",
        reply_markup=cancel_button(),
        parse_mode="HTML"
    )
    await state.set_state(PayoutFSM.waiting_deal_number)
    await callback.answer()

@dp.message(PayoutFSM.waiting_deal_number)
async def process_deal_number(message: Message, state: FSMContext):
    await state.update_data(deal_number=message.text.strip())
    await message.answer(
        f"<tg-emoji emoji-id='{EMOJI_HANDSHAKE}'>🤝</tg-emoji> <b>Введите ссылку на NFT подарок</b> (например, https://t.me/nft/PlushPepe-111):",
        reply_markup=cancel_button(),
        parse_mode="HTML"
    )
    await state.set_state(PayoutFSM.waiting_nft_link)

@dp.message(PayoutFSM.waiting_nft_link)
async def process_nft_link(message: Message, state: FSMContext):
    nft_link = message.text.strip()
    if not nft_link.startswith("https://t.me/nft/"):
        await message.answer(
            f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Неверный формат ссылки. Ссылка должна начинаться с https://t.me/nft/ ... Попробуйте снова:",
            reply_markup=cancel_button(),
            parse_mode="HTML"
        )
        return
    await state.update_data(nft_link=nft_link)
    await message.answer(
        f"<tg-emoji emoji-id='{EMOJI_CAMERA}'>📸</tg-emoji> <b>Пришлите скриншоты/фото</b> подтверждения передачи NFT мамонта.\n"
        "Можно отправить несколько фото (по одному сообщению). После всех фото нажмите /done",
        reply_markup=cancel_button(),
        parse_mode="HTML"
    )
    await state.update_data(photos=[])
    await state.set_state(PayoutFSM.waiting_photos)

@dp.message(PayoutFSM.waiting_photos, lambda m: m.photo)
async def process_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get('photos', [])
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(photos=photos)
    await message.answer(f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> Фото {len(photos)} добавлено. Отправьте ещё или /done", parse_mode="HTML")

@dp.message(PayoutFSM.waiting_photos, Command("done"))
async def done_photos(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get('photos', [])
    if not photos:
        await message.answer(f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Вы не отправили ни одного фото. Пожалуйста, отправьте хотя бы одно фото перед /done", parse_mode="HTML")
        return
    await message.answer(
        f"<tg-emoji emoji-id='{EMOJI_DIAMOND}'>💎</tg-emoji> <b>Введите ваш TON-кошелёк</b> (адрес для выплаты):",
        reply_markup=cancel_button(),
        parse_mode="HTML"
    )
    await state.set_state(PayoutFSM.waiting_wallet)

@dp.message(PayoutFSM.waiting_wallet)
async def process_wallet(message: Message, state: FSMContext):
    wallet = message.text.strip()
    if not (wallet.startswith("EQ") or wallet.startswith("UQ")) or len(wallet) < 40:
        await message.answer(f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Неверный формат TON-кошелька. Адрес должен начинаться с EQ или UQ и быть длиной ~48 символов. Попробуйте снова:", parse_mode="HTML")
        return
    await state.update_data(wallet=wallet)
    data = await state.get_data()
    text = (
        f"<b>Проверьте данные заявки:</b>\n\n"
        f"<tg-emoji emoji-id='{EMOJI_PENCIL}'>✍️</tg-emoji> Номер сделки: {data['deal_number']}\n"
        f"<tg-emoji emoji-id='{EMOJI_HANDSHAKE}'>🤝</tg-emoji> Ссылка на NFT: {data['nft_link']}\n"
        f"<tg-emoji emoji-id='{EMOJI_DIAMOND}'>💎</tg-emoji> TON-кошелёк: <code>{wallet}</code>\n"
        f"<tg-emoji emoji-id='{EMOJI_CAMERA}'>📸</tg-emoji> Фото: {len(data['photos'])} шт.\n\n"
        f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> Подтверждаете создание заявки?"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, подтвердить", callback_data="confirm_request", icon_custom_emoji_id=EMOJI_CHECK)],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_request", icon_custom_emoji_id=EMOJI_CROSS)]
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(PayoutFSM.waiting_confirm)

@dp.callback_query(lambda c: c.data == "confirm_request")
async def confirm_request(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    username = callback.from_user.username or "без_username"
    deal_number = data['deal_number']
    nft_link = data['nft_link']
    wallet = data['wallet']
    photos = data['photos']

    req_id = add_request(user_id, username, deal_number, nft_link, wallet, photos)

    admin_text = (
        f"🆕 <b>Новая заявка на выплату #{req_id}</b>\n"
        f"👤 Пользователь: @{username} (ID {user_id})\n"
        f"📄 Номер сделки: {deal_number}\n"
        f"🤝 NFT ссылка: {nft_link}\n"
        f"💎 Кошелёк: <code>{wallet}</code>\n"
        f"📸 Фото: {len(photos)} шт."
    )
    media_group = [InputMediaPhoto(media=photo) for photo in photos]
    try:
        await bot.send_media_group(ADMIN_ID, media=media_group)
    except Exception as e:
        print(f"Ошибка отправки фото админу: {e}")
    await bot.send_message(ADMIN_ID, admin_text, reply_markup=admin_buttons(req_id), parse_mode="HTML")

    if CHAT_ID != ADMIN_ID:
        try:
            await bot.send_media_group(CHAT_ID, media=media_group)
        except Exception as e:
            print(f"Ошибка отправки фото в чат: {e}")
        await bot.send_message(CHAT_ID, admin_text, reply_markup=admin_buttons(req_id), parse_mode="HTML")

    await callback.message.edit_text(f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> Ваша заявка отправлена администратору. Ожидайте обработки.", parse_mode="HTML")
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_request")
async def cancel_request(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Создание заявки отменено.", parse_mode="HTML")
    await state.clear()
    await callback.answer()

# ---------- Админская обработка ----------
@dp.callback_query(lambda c: c.data.startswith("approve_"))
async def admin_approve(callback: CallbackQuery, state: FSMContext):
    req_id = int(callback.data.split("_")[1])
    request = get_request(req_id)
    if not request or request['status'] != 'pending':
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    await callback.message.answer(
        f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> Заявка #{req_id}\nВведите сумму выплаты (например: 5 TON, 7 TON, 2,3 TON):",
        parse_mode="HTML"
    )
    await state.update_data(req_id=req_id)
    await state.set_state(AdminFSM.waiting_amount)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("reject_"))
async def admin_reject(callback: CallbackQuery):
    req_id = int(callback.data.split("_")[1])
    request = get_request(req_id)
    if not request or request['status'] != 'pending':
        await callback.answer("❌ Заявка уже обработана", show_alert=True)
        return
    update_request(req_id, 'rejected')
    user_id = request['user_id']
    await bot.send_message(user_id, f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Ваша заявка на выплату отклонена. Свяжитесь с администратором.", parse_mode="HTML")
    await callback.message.edit_text(f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Заявка #{req_id} отклонена.", parse_mode="HTML")
    await callback.answer()

@dp.message(AdminFSM.waiting_amount)
async def process_amount(message: Message, state: FSMContext):
    amount_text = message.text.strip()
    match = re.match(r"^(\d+(?:[.,]\d+)?)\s*(TON)?$", amount_text, re.IGNORECASE)
    if not match:
        await message.answer(f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Введите сумму в формате: 7 TON или 2,3 TON (запятая или точка).", parse_mode="HTML")
        return
    amount_str = match.group(1).replace(',', '.')
    amount = round(float(amount_str), 3)
    data = await state.get_data()
    req_id = data['req_id']
    request = get_request(req_id)
    if not request:
        await message.answer(f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Ошибка: заявка не найдена", parse_mode="HTML")
        await state.clear()
        return
    update_request(req_id, 'approved', str(amount))
    user_id = request['user_id']
    username = request['username']
    nft_link = request['nft_link']
    
    # Уведомление пользователю
    await bot.send_message(user_id, f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> Ваша выплата одобрена! Сумма: {amount} TON\nСредства будут отправлены в ближайшее время.", parse_mode="HTML")
    
    # Сообщение в чат/тему "Новый профит"
    chat_msg = (
        f"<blockquote>"
        f"<tg-emoji emoji-id='{EMOJI_MONEY}'>💵</tg-emoji> Новый профит <tg-emoji emoji-id='{EMOJI_MONEY2}'>💰</tg-emoji>\n"
        f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✔️</tg-emoji> <b>ВЫПЛАЧЕНО {amount} TON</b>\n"
        f"ВОРКЕР - @{username}\n"
        f"НФТ - {nft_link} <tg-emoji emoji-id='{EMOJI_HANDSHAKE}'>🤝</tg-emoji>\n"
        f"</blockquote>"
    )
    try:
        if THREAD_ID:
            await bot.send_message(CHAT_ID, chat_msg, parse_mode="HTML", message_thread_id=THREAD_ID)
        else:
            await bot.send_message(CHAT_ID, chat_msg, parse_mode="HTML")
        await message.answer(f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> Заявка #{req_id} подтверждена. Сообщение отправлено в чат.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"<tg-emoji emoji-id='{EMOJI_CROSS}'>❌</tg-emoji> Ошибка при отправке сообщения в чат: {e}\nПроверьте CHAT_ID, THREAD_ID и права бота.", parse_mode="HTML")
        print(f"Ошибка отправки в CHAT_ID={CHAT_ID}, THREAD_ID={THREAD_ID}: {e}")
    await state.clear()

# ---------- Запуск ----------
async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен")
    print(f"ADMIN_ID: {ADMIN_ID}")
    print(f"CHAT_ID: {CHAT_ID}")
    print(f"THREAD_ID: {THREAD_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())