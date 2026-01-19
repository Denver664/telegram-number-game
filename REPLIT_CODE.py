import os
import json
import logging
import random
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    filters, ContextTypes
)
import google.generativeai as genai

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ключі API
TELEGRAM_TOKEN = "8480004036:AAHPjL-RiItdX6eT-QKyBopkxpfrmA2aDVs"
GOOGLE_AI_API_KEY = "AIzaSyAbK4LMlTsR2MxlG5R76Nlx6RJIyAD_FhY"

# Ініціалізація Google AI
genai.configure(api_key=GOOGLE_AI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Файл для збереження рекордів
LEADERBOARD_FILE = "leaderboard.json"

# Словник для зберігання стану гри
game_state: Dict[int, Dict[str, Any]] = {}

# ======================== ФУНКЦІЇ РОБОТИ З ТАБЛИЦЕЮ РЕКОРДІВ ========================

def load_leaderboard() -> List[Dict[str, Any]]:
    """Завантажує таблицю рекордів з файлу"""
    if Path(LEADERBOARD_FILE).exists():
        with open(LEADERBOARD_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_leaderboard(leaderboard: List[Dict[str, Any]]):
    """Зберігає таблицю рекордів у файл"""
    with open(LEADERBOARD_FILE, 'w', encoding='utf-8') as f:
        json.dump(leaderboard, f, ensure_ascii=False, indent=2)

def add_record(username: str, mode: str, attempts: int, success: bool):
    """Додає новий рекорд до таблиці"""
    leaderboard = load_leaderboard()
    record = {
        "username": username,
        "mode": mode,
        "attempts": attempts,
        "success": success,
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%d.%m.%Y %H:%M")
    }
    leaderboard.append(record)
    save_leaderboard(leaderboard)

def format_leaderboard() -> str:
    """Форматує таблицю рекордів для виведення"""
    leaderboard = load_leaderboard()
    successful = [r for r in leaderboard if r["success"]]
    
    if not successful:
        return "📊 Таблиця рекордів порожня. Будь першим!"
    
    successful.sort(key=lambda x: (x["attempts"], x["timestamp"]))
    
    text = "🏆 ТОП РЕКОРДІВ:\n\n"
    for i, record in enumerate(successful[:10], 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}️⃣"
        text += f"{emoji} {record['username']} ({record['mode']})\n"
        text += f"   🎯 {record['attempts']} спроб | {record['date']}\n\n"
    
    return text

# ======================== ФУНКЦІЇ МЕНЮ ========================

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Головне меню"""
    keyboard = [
        [KeyboardButton("🤖 AI вгадує"), KeyboardButton("🎯 Ти вгадуєш")],
        [KeyboardButton("🏆 Рекорди"), KeyboardButton("❓ Допомога")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ======================== РЕЖИМ 1: AI ВГАДУЄ ЧИСЛО ========================

async def ai_guess_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Починає режим, де AI вгадує число"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    logger.info(f"👤 {username} (ID: {user_id}) розпочав режим 'AI вгадує'")
    
    game_state[user_id] = {
        "mode": "ai_guess",
        "ai_min": 1,
        "ai_max": 100,
        "attempts": 0,
        "username": username,
        "finished": False
    }
    
    # Перша спроба AI
    guess = (game_state[user_id]["ai_min"] + game_state[user_id]["ai_max"]) // 2
    game_state[user_id]["last_guess"] = guess
    game_state[user_id]["attempts"] += 1
    
    keyboard = [
        [InlineKeyboardButton("✅ Це число!", callback_data="ai_correct")],
        [InlineKeyboardButton("⬆️ Більше", callback_data="ai_higher")],
        [InlineKeyboardButton("⬇️ Менше", callback_data="ai_lower")],
        [InlineKeyboardButton("🚫 Вихід", callback_data="ai_exit")]
    ]
    
    await update.message.reply_text(
        f"🤖 Я буду вгадувати твоє число (від 1 до 100)!\n\n"
        f"Моя перша спроба: **{guess}**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def ai_guess_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє відповідь користувача у режимі AI вгадування"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in game_state:
        await query.answer("Гра не почата. Виберіть режим", show_alert=True)
        return
    
    state = game_state[user_id]
    
    if query.data == "ai_correct":
        # AI вгадав правильно!
        state["finished"] = True
        logger.info(f"✅ {state['username']} завершив режим AI - вгадав за {state['attempts']} спроб")
        add_record(state["username"], "🤖 AI вгадує", state["attempts"], True)
        
        await query.edit_message_text(
            f"🎉 Я вгадав твоє число за **{state['attempts']} спроб**!\n\n"
            f"Молодець! 👏"
        )
        await query.message.reply_text(
            "Бажаєш грати ще?",
            reply_markup=main_menu_keyboard()
        )
        
    elif query.data == "ai_higher":
        # Число більше
        state["ai_min"] = state["last_guess"] + 1
        
        if state["ai_min"] > state["ai_max"]:
            await query.answer("Ви дали суперечливі відповіді!", show_alert=True)
            return
        
        guess = (state["ai_min"] + state["ai_max"]) // 2
        state["last_guess"] = guess
        state["attempts"] += 1
        
        keyboard = [
            [InlineKeyboardButton("✅ Це число!", callback_data="ai_correct")],
            [InlineKeyboardButton("⬆️ Більше", callback_data="ai_higher")],
            [InlineKeyboardButton("⬇️ Менше", callback_data="ai_lower")],
            [InlineKeyboardButton("🚫 Вихід", callback_data="ai_exit")]
        ]
        
        await query.edit_message_text(
            f"Спроба {state['attempts']}: **{guess}**?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
    elif query.data == "ai_lower":
        # Число менше
        state["ai_max"] = state["last_guess"] - 1
        
        if state["ai_min"] > state["ai_max"]:
            await query.answer("Ви дали суперечливі відповіді!", show_alert=True)
            return
        
        guess = (state["ai_min"] + state["ai_max"]) // 2
        state["last_guess"] = guess
        state["attempts"] += 1
        
        keyboard = [
            [InlineKeyboardButton("✅ Це число!", callback_data="ai_correct")],
            [InlineKeyboardButton("⬆️ Більше", callback_data="ai_higher")],
            [InlineKeyboardButton("⬇️ Менше", callback_data="ai_lower")],
            [InlineKeyboardButton("🚫 Вихід", callback_data="ai_exit")]
        ]
        
        await query.edit_message_text(
            f"Спроба {state['attempts']}: **{guess}**?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
    elif query.data == "ai_exit":
        # Вихід з гри
        logger.info(f"❌ {state['username']} вийшов з режиму AI")
        add_record(state["username"], "🤖 AI вгадує", state["attempts"], False)
        
        await query.edit_message_text(f"❌ Гра завершена.")
        await query.message.reply_text(
            "Вибери режим:",
            reply_markup=main_menu_keyboard()
        )
        del game_state[user_id]
    
    await query.answer()

# ======================== РЕЖИМ 2: КОРИСТУВАЧ ВГАДУЄ ЧИСЛО AI ========================

async def user_guess_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Починає режим, де користувач вгадує число AI"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    
    ai_number = random.randint(1, 100)
    logger.info(f"👤 {username} (ID: {user_id}) розпочав режим 'Ти вгадуєш'. Загадане число: {ai_number}")
    
    game_state[user_id] = {
        "mode": "user_guess",
        "ai_number": ai_number,
        "attempts": 0,
        "username": username,
        "variants": [],
        "max_attempts": 3
    }
    
    await update.message.reply_text(
        f"🎯 Я загадав число від 1 до 100!\n"
        f"У тебе є {game_state[user_id]['max_attempts']} спроб.\n\n"
        f"Натисни 'Генерувати варіанти'!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Генерувати 3 варіанти", callback_data="generate_variants")],
            [InlineKeyboardButton("🚫 Вихід", callback_data="user_guess_exit")]
        ])
    )

async def generate_variants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерує 3 варіанти для вгадування"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in game_state or game_state[user_id]["mode"] != "user_guess":
        await query.answer("Гра не почата", show_alert=True)
        return
    
    state = game_state[user_id]
    state["attempts"] += 1
    
    ai_num = state["ai_number"]
    
    # Генеруємо 3 варіанти (один правильний)
    variant1 = random.randint(1, 100)
    while variant1 == ai_num:
        variant1 = random.randint(1, 100)
    
    variant2 = random.randint(1, 100)
    while variant2 == ai_num or variant2 == variant1:
        variant2 = random.randint(1, 100)
    
    variants = [ai_num, variant1, variant2]
    random.shuffle(variants)
    state["variants"] = variants
    
    keyboard = [
        [InlineKeyboardButton(f"📌 {variants[0]}", callback_data=f"user_choice_{variants[0]}")],
        [InlineKeyboardButton(f"📌 {variants[1]}", callback_data=f"user_choice_{variants[1]}")],
        [InlineKeyboardButton(f"📌 {variants[2]}", callback_data=f"user_choice_{variants[2]}")],
    ]
    
    if state["attempts"] < state["max_attempts"]:
        keyboard.append([InlineKeyboardButton("🎲 Нові варіанти", callback_data="generate_variants")])
    
    await query.edit_message_text(
        f"🎯 Вибери число (спроба {state['attempts']}/{state['max_attempts']}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await query.answer()

async def user_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє вибір користувача"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in game_state or game_state[user_id]["mode"] != "user_guess":
        await query.answer("Гра не почата", show_alert=True)
        return
    
    state = game_state[user_id]
    choice = int(query.data.split("_")[2])
    ai_num = state["ai_number"]
    
    if choice == ai_num:
        # Користувач вгадав!
        logger.info(f"✅ {state['username']} вгадав число - {state['attempts']} спроб")
        add_record(state["username"], "🎯 Ти вгадуєш", state["attempts"], True)
        
        await query.edit_message_text(
            f"🎉 ПРАВИЛЬНО! Число було **{ai_num}**!\n\n"
            f"Ти вгадав за **{state['attempts']} спроб**! 👏"
        )
        await query.message.reply_text(
            "Грай ще!",
            reply_markup=main_menu_keyboard()
        )
        del game_state[user_id]
        
    else:
        # Неправильно
        if state["attempts"] >= state["max_attempts"]:
            # Спроби закінчилися
            logger.info(f"❌ {state['username']} не вгадав число - {state['attempts']} спроб")
            add_record(state["username"], "🎯 Ти вгадуєш", state["attempts"], False)
            
            await query.edit_message_text(
                f"❌ НЕПРАВИЛЬНО! Число було **{ai_num}**\n\n"
                f"Спроби закінчилися... 😢"
            )
            await query.message.reply_text(
                "Грай ще!",
                reply_markup=main_menu_keyboard()
            )
            del game_state[user_id]
        else:
            # Залишилися спроби
            remaining = state["max_attempts"] - state["attempts"]
            
            if choice < ai_num:
                hint = f"💡 Підказка: число **більше** за {choice}"
            else:
                hint = f"💡 Підказка: число **менше** за {choice}"
            
            await query.edit_message_text(
                f"❌ НЕПРАВИЛЬНО!\n\n{hint}\n\n"
                f"Залишилось спроб: {remaining}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎲 Генерувати нові варіанти", callback_data="generate_variants")],
                    [InlineKeyboardButton("🚫 Здатися", callback_data="user_guess_exit")]
                ])
            )
    
    await query.answer()

async def user_guess_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вихід з режиму користувача"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id in game_state:
        ai_num = game_state[user_id].get("ai_number", "?")
        logger.info(f"❌ {game_state[user_id]['username']} вийшов з режиму")
        del game_state[user_id]
    else:
        ai_num = "?"
    
    await query.edit_message_text(
        f"❌ Гра завершена. Число було **{ai_num}**",
        parse_mode="Markdown"
    )
    await query.message.reply_text(
        "Вибери режим:",
        reply_markup=main_menu_keyboard()
    )
    await query.answer()

# ======================== ТАБЛИЦЯ РЕКОРДІВ ========================

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує таблицю рекордів"""
    text = format_leaderboard()
    
    await update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

# ======================== ДОВІДКА ========================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує довідку"""
    await update.message.reply_text(
        "❓ ДОВІДКА\n\n"
        "🤖 **AI вгадує**: AI намагається вгадати число, яке ти задумав. "
        "Допоможи AI підказками 'Більше' або 'Менше'.\n\n"
        "🎯 **Ти вгадуєш**: Вгадай число (від 1 до 100), яке загадав AI. "
        "Тобі дається 3 спроби для вибору з 3 варіантів.\n\n"
        "🏆 **Рекорди**: Побачи найкращих гравців!\n\n"
        "Мета: вгадати число за найменшу кількість спроб!",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

# ======================== ОБРОБКА ТЕКСТОВИХ ПОВІДОМЛЕНЬ ========================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє текстові повідомлення"""
    text = update.message.text
    
    if text == "🤖 AI вгадує":
        return await ai_guess_start(update, context)
    elif text == "🎯 Ти вгадуєш":
        return await user_guess_start(update, context)
    elif text == "🏆 Рекорди":
        return await show_leaderboard(update, context)
    elif text == "❓ Допомога":
        return await help_command(update, context)
    else:
        await update.message.reply_text(
            "Вибери опцію з меню:",
            reply_markup=main_menu_keyboard()
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /start"""
    user = update.effective_user
    logger.info(f"🚀 Користувач {user.id} (@{user.username}) запустив бота")
    welcome_message = (
        f"Привіт, {user.first_name}! 👋\n"
        "🎮 Ласкаво просимо в ГРУ ЧИСЕЛ!\n\n"
        "Тут доступні режими гри:\n"
        "🤖 AI вгадує твоє число\n"
        "🎯 Ти вгадуєш число AI\n"
        "🏆 Таблиця рекордів"
    )
    await update.message.reply_text(welcome_message, reply_markup=main_menu_keyboard())

# ======================== ГОЛОВНА ФУНКЦІЯ ========================

def main():
    """Запускає бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Додаємо обробники команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("records", show_leaderboard))
    
    # Обробники callback-кнопок
    application.add_handler(CallbackQueryHandler(ai_guess_response, pattern="^ai_"))
    application.add_handler(CallbackQueryHandler(generate_variants, pattern="^generate_variants$"))
    application.add_handler(CallbackQueryHandler(user_choice, pattern="^user_choice_"))
    application.add_handler(CallbackQueryHandler(user_guess_exit, pattern="^user_guess_exit$"))
    
    # Обробник текстових повідомлень
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    logger.info("✅ Бот запущено і готовий до роботи!")
    print("✅ Бот запущено! Натисніть Ctrl+C для зупинки.")
    application.run_polling()

if __name__ == "__main__":
    main()
