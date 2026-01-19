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
TELEGRAM_TOKEN = "8025420408:AAEgGtdgsC081CanU_SLtEqVgPIbf-Hlelo"
GOOGLE_AI_API_KEY = "AIzaSyAbK4LMlTsR2MxlG5R76Nlx6RJIyAD_FhY"

# Ініціалізація Google AI
genai.configure(api_key=GOOGLE_AI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Файл для збереження рекордів
LEADERBOARD_FILE = "leaderboard.json"

# Словник для зберігання стану гри
game_state: Dict[int, Dict[str, Any]] = {}

# Словник для управління кімнатами мультиплеєра
multiplayer_rooms: Dict[str, Dict[str, Any]] = {}
user_to_room: Dict[int, str] = {}  # Зв'язок користувача з кодом кімнати

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

async def competition_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Починає змагання між користувачем і ботом"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    
    game_state[user_id] = {
        "mode": "competition",
        "stage": "waiting_user_number",
        "username": username,
        "user_number": None,
        "bot_number": random.randint(1, 100),
        "ai_min": 1,
        "ai_max": 100,
        "bot_attempts": 0,
        "user_attempts": 0,
        "winner": None
    }
    
    logger.info(f"⚡ {username} розпочав змагання. Бот загадав число: {game_state[user_id]['bot_number']}")
    
    await update.message.reply_text(
        f"⚡ ЗМАГАННЯ ПОЧИНАЄТЬСЯ!\n\n"
        f"🎮 Загадай число від 1 до 100\n"
        f"(Надішли число як звичайне повідомлення)\n\n"
        f"Потім ми одночасно намагатимемося вгадати число один одного!\n"
        f"Хто перший вгадає - той виграє! 🏆",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Вихід", callback_data="competition_exit")]
        ])
    )

async def competition_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує число від користувача для змагання"""
    user_id = update.effective_user.id
    
    if user_id not in game_state or game_state[user_id]["mode"] != "competition":
        return
    
    if game_state[user_id]["stage"] != "waiting_user_number":
        return
    
    try:
        user_number = int(update.message.text)
        if not (1 <= user_number <= 100):
            await update.message.reply_text("❌ Число повинно бути від 1 до 100!")
            return
    except ValueError:
        return
    
    state = game_state[user_id]
    state["user_number"] = user_number
    state["stage"] = "competition_running"
    
    logger.info(f"👤 {state['username']} загадав число для змагання: {user_number}")
    
    await update.message.reply_text(
        f"✅ Ти загадав число!\n\n"
        f"🤖 Я загадав число від 1 до 100\n\n"
        f"Тепер вгадуй моє число! Напиши 'більше', 'менше' або номер ➡️",
        reply_markup=main_menu_keyboard()
    )
    
    # Бот робить першу спробу
    bot_guess = 50
    state["bot_last_guess"] = bot_guess
    state["bot_attempts"] += 1
    
    await update.message.reply_text(
        f"🤖 Моя перша спроба: **{bot_guess}**\n\n"
        f"Більше чи менше твоє число?"
    )

async def competition_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє відповіді під час змагання"""
    user_id = update.effective_user.id
    
    if user_id not in game_state or game_state[user_id]["mode"] != "competition":
        return
    
    if game_state[user_id]["stage"] != "competition_running":
        return
    
    state = game_state[user_id]
    text = update.message.text.lower().strip()
    
    # Перевірка чи користувач ввів число
    try:
        guess = int(text)
        if 1 <= guess <= 100:
            state["user_attempts"] += 1
            
            if guess == state["bot_number"]:
                # Користувач вгадав!
                state["winner"] = "user"
                add_record(state["username"], "⚡ Змагання", state["user_attempts"], True)
                
                await update.message.reply_text(
                    f"🎉 ТИ ПЕРЕМІГ! 🎉\n\n"
                    f"Ти вгадав моє число ({state['bot_number']}) за {state['user_attempts']} спроб!\n"
                    f"Я не встиг вгадати твоє число... 😢\n\n"
                    f"👑 ЧЕМПІОН!"
                )
                del game_state[user_id]
                await update.message.reply_text("Вибери режим:", reply_markup=main_menu_keyboard())
                return
            elif guess < state["bot_number"]:
                await update.message.reply_text(f"💡 Мое число **більше** за {guess}")
            else:
                await update.message.reply_text(f"💡 Мое число **менше** за {guess}")
            
            return
    except ValueError:
        pass
    
    # Обробка відповідей "більше" / "менше"
    if "більше" in text or "вище" in text or "більш" in text:
        state["ai_min"] = state["bot_last_guess"] + 1
        
        if state["ai_min"] > state["ai_max"]:
            await update.message.reply_text("❌ Ти дав суперечливі відповіді!")
            return
        
        bot_guess = (state["ai_min"] + state["ai_max"]) // 2
        state["bot_last_guess"] = bot_guess
        state["bot_attempts"] += 1
        
        # Перевірка чи бот вгадав
        if bot_guess == state["user_number"]:
            state["winner"] = "bot"
            add_record(state["username"], "⚡ Змагання", state["user_attempts"], False)
            
            await update.message.reply_text(
                f"🤖 БОТА ПЕРЕМОГА! 🤖\n\n"
                f"Я вгадав твоє число ({state['user_number']}) за {state['bot_attempts']} спроб!\n"
                f"Ти встиг зробити {state['user_attempts']} спроб...\n\n"
                f"Я сильніший! 🏆"
            )
            del game_state[user_id]
            await update.message.reply_text("Вибери режим:", reply_markup=main_menu_keyboard())
            return
        
        await update.message.reply_text(f"🤖 Спроба {state['bot_attempts']}: **{bot_guess}**")
        
    elif "менше" in text or "нижче" in text or "менш" in text:
        state["ai_max"] = state["bot_last_guess"] - 1
        
        if state["ai_min"] > state["ai_max"]:
            await update.message.reply_text("❌ Ти дав суперечливі відповіді!")
            return
        
        bot_guess = (state["ai_min"] + state["ai_max"]) // 2
        state["bot_last_guess"] = bot_guess
        state["bot_attempts"] += 1
        
        # Перевірка чи бот вгадав
        if bot_guess == state["user_number"]:
            state["winner"] = "bot"
            add_record(state["username"], "⚡ Змагання", state["user_attempts"], False)
            
            await update.message.reply_text(
                f"🤖 БОТА ПЕРЕМОГА! 🤖\n\n"
                f"Я вгадав твоє число ({state['user_number']}) за {state['bot_attempts']} спроб!\n"
                f"Ти встиг зробити {state['user_attempts']} спроб...\n\n"
                f"Я сильніший! 🏆"
            )
            del game_state[user_id]
            await update.message.reply_text("Вибери режим:", reply_markup=main_menu_keyboard())
            return
        
        await update.message.reply_text(f"🤖 Спроба {state['bot_attempts']}: **{bot_guess}**")

async def competition_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вихід з змагання"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id in game_state:
        del game_state[user_id]
    
    await query.edit_message_text("❌ Змагання скасовано.")
    await query.message.reply_text("Вибери режим:", reply_markup=main_menu_keyboard())
    await query.answer()

# ======================== МУЛЬТИПЛЕЄР: ГРА З ДРУГОМ ========================

def generate_room_code() -> str:
    """Генерує унікальний код кімнати"""
    import string
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(6))

async def multiplayer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Створює нову кімнату для гри з другом"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    
    room_code = generate_room_code()
    
    # Створюємо кімнату
    multiplayer_rooms[room_code] = {
        "player1_id": user_id,
        "player1_name": username,
        "player2_id": None,
        "player2_name": None,
        "player1_number": None,
        "player2_number": None,
        "stage": "waiting_player2",
        "player1_attempts": 0,
        "player2_attempts": 0,
        "winner": None
    }
    
    user_to_room[user_id] = room_code
    
    logger.info(f"👥 {username} (ID: {user_id}) створив кімнату: {room_code}")
    
    await update.message.reply_text(
        f"👥 ГОРА З ДРУГОМ\n\n"
        f"✅ Кімната створена!\n\n"
        f"🔑 КОД КІМНАТИ: **{room_code}**\n\n"
        f"Надішли цей код своєму другу.\n"
        f"Він зможе приєднатися за допомогою команди /join_room {room_code}\n\n"
        f"💬 Очікування другого гравця...",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Скасувати", callback_data=f"multiplayer_cancel_{room_code}")]
        ])
    )

async def join_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приєднується до існуючої кімнати"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    
    # Отримуємо код кімнати з команди
    try:
        room_code = context.args[0].upper() if context.args else None
    except (IndexError, AttributeError):
        await update.message.reply_text("❌ Використовуй: /join_room КОД")
        return
    
    if not room_code or room_code not in multiplayer_rooms:
        await update.message.reply_text(f"❌ Кімната **{room_code}** не знайдена!")
        return
    
    room = multiplayer_rooms[room_code]
    
    if room["player2_id"] is not None:
        await update.message.reply_text(f"❌ Кімната **{room_code}** вже повна!")
        return
    
    if user_id == room["player1_id"]:
        await update.message.reply_text("❌ Ти не можеш приєднатися до своєї кімнати!")
        return
    
    # Гравець 2 приєднується
    room["player2_id"] = user_id
    room["player2_name"] = username
    room["stage"] = "waiting_numbers"
    user_to_room[user_id] = room_code
    
    logger.info(f"👥 {username} (ID: {user_id}) приєднався до кімнати: {room_code}")
    
    # Повідомляємо обох гравців
    await update.message.reply_text(
        f"👥 ГРА ПОЧИНАЄТЬСЯ!\n\n"
        f"⚔️ Супротивник: **{room['player1_name']}**\n\n"
        f"🎮 Тепер загадай число від 1 до 100\n"
        f"(Надішли число як звичайне повідомлення)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Вийти", callback_data=f"multiplayer_exit_{room_code}")]
        ])
    )
    
    # Context потрібен для відправки повідомлення першому гравцю
    # Можемо зберегти chat_id у контексті
    if hasattr(context, 'bot'):
        try:
            await context.bot.send_message(
                chat_id=room["player1_id"],
                text=f"👥 ГРА ПОЧИНАЄТЬСЯ!\n\n⚔️ Супротивник: **{username}**\n\n🎮 Тепер загадай число від 1 до 100\n(Надішли число як звичайне повідомлення)",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Вийти", callback_data=f"multiplayer_exit_{room_code}")]
                ])
            )
        except:
            pass

async def multiplayer_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує число від гравця"""
    user_id = update.effective_user.id
    
    if user_id not in user_to_room:
        return
    
    room_code = user_to_room[user_id]
    if room_code not in multiplayer_rooms:
        return
    
    room = multiplayer_rooms[room_code]
    
    if room["stage"] != "waiting_numbers":
        return
    
    try:
        number = int(update.message.text)
        if not (1 <= number <= 100):
            await update.message.reply_text("❌ Число повинно бути від 1 до 100!")
            return
    except ValueError:
        return
    
    # Визначаємо якого гравця
    is_player1 = user_id == room["player1_id"]
    
    if is_player1:
        room["player1_number"] = number
        logger.info(f"👤 {room['player1_name']} загадав число для мультиплеєра: {number}")
    else:
        room["player2_number"] = number
        logger.info(f"👤 {room['player2_name']} загадав число для мультиплеєра: {number}")
    
    # Перевіримо чи обидва гравці загадали числа
    if room["player1_number"] is not None and room["player2_number"] is not None:
        room["stage"] = "game_running"
        
        # Повідомляємо обом гравцям що гра почалася
        keyboard = [
            [InlineKeyboardButton("🔢 1", callback_data=f"mp_guess_{room_code}_1")],
            [InlineKeyboardButton("🔢 25", callback_data=f"mp_guess_{room_code}_25")],
            [InlineKeyboardButton("🔢 50", callback_data=f"mp_guess_{room_code}_50")],
            [InlineKeyboardButton("🔢 75", callback_data=f"mp_guess_{room_code}_75")],
            [InlineKeyboardButton("🔢 100", callback_data=f"mp_guess_{room_code}_100")],
            [InlineKeyboardButton("📝 Своє число", callback_data=f"mp_custom_{room_code}")],
            [InlineKeyboardButton("💡 Підказка", callback_data=f"mp_hint_{room_code}")],
            [InlineKeyboardButton("❌ Вийти", callback_data=f"multiplayer_exit_{room_code}")]
        ]
        
        msg_text = f"⚔️ ГРА РОЗПОЧАЛАСЬ!\n\n🎯 Вгадай число супротивника (1-100)!\n\nВибери число або натисни кнопку:"
        
        if hasattr(context, 'bot'):
            try:
                await context.bot.send_message(
                    chat_id=room["player1_id"],
                    text=msg_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                await context.bot.send_message(
                    chat_id=room["player2_id"],
                    text=msg_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                pass

async def multiplayer_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє здогад гравця"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_to_room:
        await query.answer("❌ Ви не в кімнаті", show_alert=True)
        return
    
    room_code = user_to_room[user_id]
    if room_code not in multiplayer_rooms:
        await query.answer("❌ Кімната не знайдена", show_alert=True)
        return
    
    room = multiplayer_rooms[room_code]
    
    if room["stage"] != "game_running" and room["stage"] != "game_guessing":
        await query.answer("❌ Гра не в статусі для здогадів", show_alert=True)
        return
    
    room["stage"] = "game_guessing"
    
    # Отримуємо число з callback_data
    data_parts = query.data.split("_")
    guess = int(data_parts[2])
    
    is_player1 = user_id == room["player1_id"]
    opponent_number = room["player2_number"] if is_player1 else room["player1_number"]
    opponent_id = room["player2_id"] if is_player1 else room["player1_id"]
    
    if is_player1:
        room["player1_attempts"] += 1
        player_name = room["player1_name"]
    else:
        room["player2_attempts"] += 1
        player_name = room["player2_name"]
    
    await query.answer()
    
    if guess == opponent_number:
        # ПЕРЕМОГА!
        room["stage"] = "finished"
        room["winner"] = "player1" if is_player1 else "player2"
        
        winner_attempts = room["player1_attempts"] if is_player1 else room["player2_attempts"]
        loser_name = room["player2_name"] if is_player1 else room["player1_name"]
        
        add_record(player_name, "👥 Гра з другом", winner_attempts, True)
        add_record(loser_name, "👥 Гра з другом", (room["player2_attempts"] if is_player1 else room["player1_attempts"]), False)
        
        await query.edit_message_text(
            f"🎉 ПЕРЕМОГА! 🎉\n\n"
            f"👑 {player_name} вгадав число {opponent_number} за {winner_attempts} спроб!\n\n"
            f"⚔️ {loser_name} не встиг...\n\n"
            f"🏆 ЧЕМПІОН: {player_name}!"
        )
        
        if hasattr(context, 'bot'):
            try:
                await context.bot.send_message(
                    chat_id=opponent_id,
                    text=f"❌ ПРОГРАШ!\n\n👑 {player_name} вгадав число {opponent_number} за {winner_attempts} спроб!\n\nТвоє число було {opponent_number}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu_main")]])
                )
            except:
                pass
        
        # Очищуємо комнату через 5 хвилин
        del multiplayer_rooms[room_code]
        del user_to_room[room["player1_id"]]
        if room["player2_id"]:
            del user_to_room[room["player2_id"]]
        
        await query.message.reply_text("Вибери режим:", reply_markup=main_menu_keyboard())
    else:
        if guess < opponent_number:
            hint = "💡 Число БІЛЬШЕ"
        else:
            hint = "💡 Число МЕНШЕ"
        
        await query.edit_message_text(
            f"❌ Неправильно!\n\n{hint}\n\n"
            f"Спроби: {room['player1_attempts'] if is_player1 else room['player2_attempts']}"
        )

async def multiplayer_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Дає підказку супротивнику"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_to_room:
        await query.answer("❌ Ви не в кімнаті", show_alert=True)
        return
    
    room_code = user_to_room[user_id]
    if room_code not in multiplayer_rooms:
        await query.answer("❌ Кімната не знайдена", show_alert=True)
        return
    
    room = multiplayer_rooms[room_code]
    
    is_player1 = user_id == room["player1_id"]
    your_number = room["player1_number"] if is_player1 else room["player2_number"]
    opponent_id = room["player2_id"] if is_player1 else room["player1_id"]
    
    await query.answer()
    
    await query.message.reply_text("📝 Напиши підказку для супротивника (більше/менше):")

async def multiplayer_custom_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить своє число для здогаду"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_to_room:
        await query.answer("❌ Ви не в кімнаті", show_alert=True)
        return
    
    room_code = user_to_room[user_id]
    if room_code not in multiplayer_rooms:
        await query.answer("❌ Кімната не знайдена", show_alert=True)
        return
    
    room = multiplayer_rooms[room_code]
    
    # Зберігаємо стан що чекаємо вводу числа
    user_awaiting_input = f"awaiting_guess_{room_code}"
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    context.user_data[user_awaiting_input] = True
    
    await query.answer()
    await query.edit_message_text("📝 Введи число (1-100):")

async def multiplayer_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вихід з мультиплеєр гри"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Отримуємо код кімнати з callback_data
    data_parts = query.data.split("_")
    room_code = data_parts[2]
    
    if room_code not in multiplayer_rooms:
        await query.answer("❌ Кімната не знайдена", show_alert=True)
        return
    
    room = multiplayer_rooms[room_code]
    
    # Визначаємо якого гравця
    is_player1 = user_id == room["player1_id"]
    opponent_id = room["player2_id"] if is_player1 else room["player1_id"]
    
    # Очищуємо дані
    if room_code in user_to_room:
        if user_id in user_to_room and user_to_room[user_id] == room_code:
            del user_to_room[user_id]
    
    if room["stage"] == "waiting_player2":
        # Ще ніхто не приєднався
        await query.edit_message_text("❌ Кімната скасована.")
        del multiplayer_rooms[room_code]
    else:
        # Гра була розпочата
        await query.edit_message_text("❌ Ви вийшли з гри.")
        
        if opponent_id and hasattr(context, 'bot'):
            try:
                opponent_name = room["player1_name"] if not is_player1 else room["player2_name"]
                await context.bot.send_message(
                    chat_id=opponent_id,
                    text=f"❌ Супротивник ({opponent_name}) вийшов з гри!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu_main")]])
                )
                if opponent_id in user_to_room:
                    del user_to_room[opponent_id]
            except:
                pass
        
        del multiplayer_rooms[room_code]
    
    await query.answer()
    await query.message.reply_text("Вибери режим:", reply_markup=main_menu_keyboard())

async def multiplayer_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування очікування другого гравця"""
    query = update.callback_query
    user_id = query.from_user.id
    
    data_parts = query.data.split("_")
    room_code = data_parts[2]
    
    if room_code not in multiplayer_rooms:
        await query.answer("❌ Кімната не знайдена", show_alert=True)
        return
    
    room = multiplayer_rooms[room_code]
    
    if room["player1_id"] != user_id:
        await query.answer("❌ Тільки створювач може скасувати", show_alert=True)
        return
    
    await query.edit_message_text("❌ Пошук скасовано.")
    del multiplayer_rooms[room_code]
    del user_to_room[user_id]
    
    await query.answer()
    await query.message.reply_text("Вибери режим:", reply_markup=main_menu_keyboard())

# ======================== ФУНКЦІЇ МЕНЮ ========================

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Головне меню"""
    keyboard = [
        [KeyboardButton("🤖 AI вгадує"), KeyboardButton("🎯 Ти вгадуєш")],
        [KeyboardButton("📊 Рівні складності"), KeyboardButton("🏃 Марафон")],
        [KeyboardButton("⏱️ Швидкісна гра"), KeyboardButton("⚡ Змагання")],
        [KeyboardButton("� Гра з другом"), KeyboardButton("📈 Моя статистика")],
        [KeyboardButton("🏆 Рекорди"), KeyboardButton("❓ Допомога")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def difficulty_keyboard() -> InlineKeyboardMarkup:
    """Клавіатура для вибору рівня складності"""
    keyboard = [
        [InlineKeyboardButton("😊 Легкий (1-50)", callback_data="difficulty_easy")],
        [InlineKeyboardButton("😐 Середній (1-100)", callback_data="difficulty_medium")],
        [InlineKeyboardButton("😤 Важкий (1-1000)", callback_data="difficulty_hard")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ======================== РЕЖИМ 1: AI ВГАДУЄ ЧИСЛО ========================

async def ai_guess_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Починає режим, де AI вгадує число"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    
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
    help_text = (
        "❓ ДОВІДКА\n\n"
        "🤖 AI вгадує\nAI намагається вгадати число, яке ти задумав.\n"
        "Допоможи AI підказками 'Більше' або 'Менше'.\n\n"
        "🎯 Ти вгадуєш\nВгадай число (від 1 до 100), яке загадав AI.\n"
        "Тобі дається 3 спроби для вибору з 3 варіантів.\n\n"
        "⚡ Змагання з ботом\nТи й AI одночасно вгадуєте число один одного!\n"
        "Хто перший вгадає - той виграє! 🏆\n\n"
        "👥 Гра з другом\nГрай 1v1 з другом! Жми кнопку, отримаєш код кімнати.\n"
        "Розповідай другу код: /join_room КОД\n"
        "Обидва вгадуєте числа - хто перший вгадає, той переміг!\n\n"
        "📊 Рівні складності\nЛегкий (1-50), Середній (1-100), Важкий (1-1000)\n\n"
        "🏃 Марафон\n5 раундів підряд, де ти вгадуєш число AI\n\n"
        "⏱️ Швидкісна гра\nГра проти часу! Вгадай число за 5 спроб\n\n"
        "🏆 Рекорди\nПобачи найкращих гравців!\n\n"
        "Мета: вгадати число за найменшу кількість спроб!"
    )
    await update.message.reply_text(help_text, reply_markup=main_menu_keyboard())

# ======================== ОБРОБКА ТЕКСТОВИХ ПОВІДОМЛЕНЬ ========================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє текстові повідомлення"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Обробка змагання з ботом
    if user_id in game_state and game_state[user_id]["mode"] == "competition":
        if game_state[user_id]["stage"] == "waiting_user_number":
            return await competition_number_input(update, context)
        elif game_state[user_id]["stage"] == "competition_running":
            return await competition_response(update, context)
    
    # Обробка мультиплеєра - введення чисел
    if user_id in user_to_room:
        room_code = user_to_room[user_id]
        if room_code in multiplayer_rooms:
            room = multiplayer_rooms[room_code]
            if room["stage"] == "waiting_numbers":
                return await multiplayer_number_input(update, context)
            elif room["stage"] == "game_guessing":
                try:
                    guess = int(text)
                    if 1 <= guess <= 100:
                        # Створюємо фальшиво callback_query для обробки здогаду
                        data = f"mp_guess_{room_code}_{guess}"
                        update.callback_query = type('obj', (object,), {
                            'data': data,
                            'from_user': update.effective_user,
                            'answer': lambda **kwargs: None,
                            'edit_message_text': lambda text, **kwargs: update.message.reply_text(text, **kwargs) if kwargs else update.message.reply_text(text),
                            'message': update.message
                        })()
                        return await multiplayer_guess(update, context)
                except ValueError:
                    pass
    
    if text == "🤖 AI вгадує":
        return await ai_guess_start(update, context)
    elif text == "🎯 Ти вгадуєш":
        return await user_guess_start(update, context)
    elif text == "📊 Рівні складності":
        await update.message.reply_text(
            "Виберіть рівень складності:",
            reply_markup=difficulty_keyboard()
        )
    elif text == "🏃 Марафон":
        return await marathon_start(update, context)
    elif text == "⏱️ Швидкісна гра":
        return await timed_game_start(update, context)
    elif text == "⚡ Змагання":
        return await competition_start(update, context)
    elif text == "👥 Гра з другом":
        return await multiplayer_start(update, context)
    elif text == "📈 Моя статистика":
        return await show_user_stats(update, context)
    elif text == "🏆 Рекорди":
        return await show_leaderboard(update, context)
    elif text == "❓ Допомога":
        return await help_command(update, context)
    else:
        await update.message.reply_text(
            "Вибери опцію з меню:",
            reply_markup=main_menu_keyboard()
        )

# ======================== РЕЖИМ: РІВНІ СКЛАДНОСТІ ========================

async def difficulty_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє вибір рівня складності"""
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name or "User"
    
    if query.data == "difficulty_easy":
        difficulty = ("easy", 1, 50, "😊 Легкий")
    elif query.data == "difficulty_medium":
        difficulty = ("medium", 1, 100, "😐 Середній")
    else:
        difficulty = ("hard", 1, 1000, "😤 Важкий")
    
    ai_number = random.randint(difficulty[1], difficulty[2])
    logger.info(f"👤 {username} (ID: {user_id}) вибрав рівень: {difficulty[3]} ({difficulty[1]}-{difficulty[2]}). Загадане число: {ai_number}")
    
    game_state[user_id] = {
        "mode": f"📊 {difficulty[3]}",
        "ai_number": ai_number,
        "attempts": 0,
        "username": username,
        "max_attempts": 3,
        "difficulty": difficulty[0]
    }
    
    await query.edit_message_text(
        f"🎯 {difficulty[3]} рівень!\n"
        f"Діапазон: {difficulty[1]} - {difficulty[2]}\n"
        f"У тебе є 3 спроби з вибором 3 варіантів.\n\n"
        f"Натисни 'Генерувати варіанти'!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Генерувати варіанти", callback_data="generate_variants")],
            [InlineKeyboardButton("🚫 Вихід", callback_data="user_guess_exit")]
        ])
    )
    await query.answer()

# ======================== РЕЖИМ: МАРАФОН ========================

async def marathon_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Починає режим Марафон (кілька раундів)"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    logger.info(f"👤 {username} (ID: {user_id}) розпочав режим 'МАРАФОН' (5 раундів)")
    
    game_state[user_id] = {
        "mode": "🏃 Марафон",
        "rounds": 0,
        "total_attempts": 0,
        "username": username,
        "marathon_rounds": 5,
        "marathon_results": []
    }
    
    await update.message.reply_text(
        "🏃 РЕЖИМ МАРАФОН!\n\n"
        "Ти вгадуватимеш число AI 5 раундів підряд.\n"
        "Всього виконаних спроб буде визначати рейтинг.\n\n"
        "Натисни 'Почати марафон'!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Почати марафон", callback_data="marathon_generate_1")],
            [InlineKeyboardButton("🚫 Відмінити", callback_data="user_guess_exit")]
        ])
    )

async def marathon_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерує варіанти для марафону"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in game_state or game_state[user_id]["mode"] != "🏃 Марафон":
        await query.answer("Марафон не почато", show_alert=True)
        return
    
    state = game_state[user_id]
    state["rounds"] += 1
    state["current_attempts"] = 0
    
    ai_number = random.randint(1, 100)
    state["marathon_number"] = ai_number
    logger.info(f"📝 Марафон раунд {state['rounds']}/5. Загадане число: {ai_number}")
    state["max_attempts"] = 3
    
    # Генеруємо варіанти
    variant1 = random.randint(1, 100)
    while variant1 == ai_number:
        variant1 = random.randint(1, 100)
    
    variant2 = random.randint(1, 100)
    while variant2 == ai_number or variant2 == variant1:
        variant2 = random.randint(1, 100)
    
    variants = [ai_number, variant1, variant2]
    random.shuffle(variants)
    
    keyboard = [
        [InlineKeyboardButton(f"📌 {variants[0]}", callback_data=f"marathon_choice_{variants[0]}")],
        [InlineKeyboardButton(f"📌 {variants[1]}", callback_data=f"marathon_choice_{variants[1]}")],
        [InlineKeyboardButton(f"📌 {variants[2]}", callback_data=f"marathon_choice_{variants[2]}")]
    ]
    
    await query.edit_message_text(
        f"🏃 МАРАФОН - Раунд {state['rounds']}/5\n\n"
        f"Вибери число:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await query.answer()

async def marathon_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє вибір у марафоні"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in game_state or game_state[user_id]["mode"] != "🏃 Марафон":
        await query.answer("Марафон не почато", show_alert=True)
        return
    
    state = game_state[user_id]
    choice = int(query.data.split("_")[2])
    ai_num = state.get("marathon_number")
    state["current_attempts"] += 1
    state["total_attempts"] += 1
    
    if choice == ai_num:
        # Правильно!
        state["marathon_results"].append({
            "round": state["rounds"],
            "attempts": state["current_attempts"],
            "success": True
        })
        
        if state["rounds"] < state["marathon_rounds"]:
            await query.edit_message_text(
                f"🎉 ВІРНО! Раунд {state['rounds']} завершено за {state['current_attempts']} спроб!\n\n"
                f"Інші раунди: {state['marathon_rounds'] - state['rounds']}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Наступний раунд", callback_data="marathon_generate_next")]
                ])
            )
        else:
            # Марафон закінчено
            total = state["total_attempts"]
            add_record(state["username"], "🏃 Марафон", total, True)
            
            results = "\n".join([f"Раунд {r['round']}: {r['attempts']} спроб ✅" 
                                for r in state["marathon_results"]])
            
            await query.edit_message_text(
                f"🏆 МАРАФОН ЗАВЕРШЕНО!\n\n"
                f"{results}\n\n"
                f"Всього спроб: {total}\n"
                f"Середнє: {total/5:.1f} спроб за раунд"
            )
            await query.message.reply_text(
                "Вибери наступну гру:",
                reply_markup=main_menu_keyboard()
            )
            del game_state[user_id]
    else:
        # Неправильно
        if state["current_attempts"] >= 3:
            state["marathon_results"].append({
                "round": state["rounds"],
                "attempts": 3,
                "success": False
            })
            
            if state["rounds"] < state["marathon_rounds"]:
                await query.edit_message_text(
                    f"❌ Невдача на раунді {state['rounds']}. Число було {ai_num}.\n\n"
                    f"Інші раунди: {state['marathon_rounds'] - state['rounds']}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("▶️ Наступний раунд", callback_data="marathon_generate_next")]
                    ])
                )
            else:
                total = state["total_attempts"]
                add_record(state["username"], "🏃 Марафон", total, False)
                
                await query.edit_message_text(
                    f"🏃 МАРАФОН ЗАВЕРШЕНО!\n\n"
                    f"Всього спроб: {total}\n"
                    f"Невдача на останньому раунді..."
                )
                await query.message.reply_text(
                    "Грай ще!",
                    reply_markup=main_menu_keyboard()
                )
                del game_state[user_id]
        else:
            await query.edit_message_text(
                f"❌ НЕПРАВИЛЬНО!\n"
                f"Залишилось спроб: {3 - state['current_attempts']}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎲 Нові варіанти", callback_data="marathon_generate_1")]
                ])
            )
    
    await query.answer()

# ======================== РЕЖИМ: ШВИДКІСНА ГРА ========================

async def timed_game_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Починає швидкісну гру з обмеженням часу"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    
    ai_number = random.randint(1, 100)
    logger.info(f"👤 {username} (ID: {user_id}) розпочав режим 'ШВИДКІСНА ГРА'. Загадане число: {ai_number}")
    
    game_state[user_id] = {
        "mode": "⏱️ Швидкісна гра",
        "ai_number": ai_number,
        "attempts": 0,
        "username": username,
        "max_attempts": 5,
        "start_time": datetime.now()
    }
    
    await update.message.reply_text(
        "⏱️ ШВИДКІСНА ГРА!\n\n"
        "Вгадай число від 1 до 100 за 5 спроб.\n"
        "Чим швидше - тим краще рейтинг!\n\n"
        "Натисни 'Генерувати варіанти'!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Генерувати 3 варіанти", callback_data="timed_generate_variants")],
            [InlineKeyboardButton("🚫 Вихід", callback_data="user_guess_exit")]
        ])
    )

async def timed_generate_variants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерує варіанти для швидкісної гри"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in game_state or game_state[user_id]["mode"] != "⏱️ Швидкісна гра":
        await query.answer("Гра не почата", show_alert=True)
        return
    
    state = game_state[user_id]
    state["attempts"] += 1
    
    ai_num = state["ai_number"]
    
    # Генеруємо варіанти
    variant1 = random.randint(1, 100)
    while variant1 == ai_num:
        variant1 = random.randint(1, 100)
    
    variant2 = random.randint(1, 100)
    while variant2 == ai_num or variant2 == variant1:
        variant2 = random.randint(1, 100)
    
    variants = [ai_num, variant1, variant2]
    random.shuffle(variants)
    
    keyboard = [
        [InlineKeyboardButton(f"📌 {variants[0]}", callback_data=f"timed_choice_{variants[0]}")],
        [InlineKeyboardButton(f"📌 {variants[1]}", callback_data=f"timed_choice_{variants[1]}")],
        [InlineKeyboardButton(f"📌 {variants[2]}", callback_data=f"timed_choice_{variants[2]}")],
    ]
    
    if state["attempts"] < state["max_attempts"]:
        keyboard.append([InlineKeyboardButton("🎲 Нові варіанти", callback_data="timed_generate_variants")])
    
    elapsed = (datetime.now() - state["start_time"]).seconds
    
    await query.edit_message_text(
        f"⏱️ ШВИДКІСНА ГРА (спроба {state['attempts']}/{state['max_attempts']})\n"
        f"Час: {elapsed}с\n\n"
        f"Вибери число:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await query.answer()

async def timed_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє вибір у швидкісній грі"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in game_state or game_state[user_id]["mode"] != "⏱️ Швидкісна гра":
        await query.answer("Гра не почата", show_alert=True)
        return
    
    state = game_state[user_id]
    choice = int(query.data.split("_")[2])
    ai_num = state["ai_number"]
    elapsed = (datetime.now() - state["start_time"]).seconds
    
    if choice == ai_num:
        # Правильно!
        add_record(state["username"], "⏱️ Швидкісна", elapsed, True)
        
        await query.edit_message_text(
            f"🎉 ВІРНО за {state['attempts']} спроб!\n"
            f"Час: {elapsed} секунд ⚡"
        )
        await query.message.reply_text(
            "Грай ще!",
            reply_markup=main_menu_keyboard()
        )
        del game_state[user_id]
    else:
        # Неправильно
        if state["attempts"] >= state["max_attempts"]:
            add_record(state["username"], "⏱️ Швидкісна", elapsed, False)
            
            await query.edit_message_text(
                f"❌ Спроби закінчилися!\n"
                f"Число було {ai_num}\n"
                f"Час: {elapsed}с"
            )
            await query.message.reply_text(
                "Грай ще!",
                reply_markup=main_menu_keyboard()
            )
            del game_state[user_id]
        else:
            remaining = state["max_attempts"] - state["attempts"]
            
            await query.edit_message_text(
                f"❌ НЕПРАВИЛЬНО!\n"
                f"Залишилось спроб: {remaining}\n"
                f"Час: {elapsed}с",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎲 Нові варіанти", callback_data="timed_generate_variants")],
                    [InlineKeyboardButton("🚫 Здатися", callback_data="user_guess_exit")]
                ])
            )
    
    await query.answer()

# ======================== РЕЖИМ: МОЯ СТАТИСТИКА ========================

async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує статистику гравця"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "User"
    
    leaderboard = load_leaderboard()
    user_records = [r for r in leaderboard if r["username"] == username]
    
    if not user_records:
        await update.message.reply_text(
            "📈 У тебе ще немає результатів.\n"
            "Почни грати, щоб побачити статистику!",
            reply_markup=main_menu_keyboard()
        )
        return
    
    total_games = len(user_records)
    successful = len([r for r in user_records if r["success"]])
    failed = total_games - successful
    
    # Статистика за режимами
    stats_by_mode = {}
    for record in user_records:
        mode = record["mode"]
        if mode not in stats_by_mode:
            stats_by_mode[mode] = {"total": 0, "success": 0, "total_attempts": 0}
        stats_by_mode[mode]["total"] += 1
        if record["success"]:
            stats_by_mode[mode]["success"] += 1
        stats_by_mode[mode]["total_attempts"] += record["attempts"]
    
    # Форматування
    text = f"📈 ТВОЯ СТАТИСТИКА (@{username})\n\n"
    text += f"📊 Загально:\n"
    text += f"  Всього ігор: {total_games}\n"
    text += f"  Перемог: {successful} ✅\n"
    text += f"  Поразок: {failed} ❌\n"
    text += f"  Рейтинг: {(successful/total_games*100):.1f}%\n\n"
    
    text += "📝 За режимами:\n"
    for mode, stats in stats_by_mode.items():
        avg_attempts = stats["total_attempts"] / stats["total"]
        text += f"  {mode}: {stats['success']}/{stats['total']} (⌀ {avg_attempts:.1f} спроб)\n"
    
    await update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник команди /start"""
    user = update.effective_user
    logger.info(f"🚀 Користувач {user.id} (@{user.username}) запустив бота")
    welcome_message = (
        f"Привіт, {user.first_name}! 👋\n"
        "🎮 Ласкаво просимо в ГРУ ЧИСЕЛ!\n\n"
        "📊 РЕЖИМИ ГРИ:\n"
        "🤖 AI вгадує - AI вгадує твоє число\n"
        "🎯 Ти вгадуєш - Вгадай число AI (3 варіанти)\n"
        "📊 Рівні складності - Легкий/Середній/Важкий\n"
        "🏃 Марафон - 5 раундів підряд\n"
        "⏱️ Швидкісна гра - Гра проти часу\n"
        "⚡ Змагання - Ти й AI вгадуєте одночасно!\n"
        "📈 Моя статистика - Твої результати\n"
        "🏆 Рекорди - ТОП гравців"
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
    application.add_handler(CommandHandler("join_room", join_room))
    
    # Обробники callback-кнопок (старі режими)
    application.add_handler(CallbackQueryHandler(ai_guess_response, pattern="^ai_"))
    application.add_handler(CallbackQueryHandler(generate_variants, pattern="^generate_variants$"))
    application.add_handler(CallbackQueryHandler(user_choice, pattern="^user_choice_"))
    application.add_handler(CallbackQueryHandler(user_guess_exit, pattern="^user_guess_exit$"))
    
    # Обробники нових режимів
    # Режим: Рівні складності
    application.add_handler(CallbackQueryHandler(difficulty_choice, pattern="^difficulty_"))
    
    # Режим: Марафон
    application.add_handler(CallbackQueryHandler(marathon_generate, pattern="^marathon_generate_"))
    application.add_handler(CallbackQueryHandler(marathon_choice, pattern="^marathon_choice_"))
    
    # Режим: Швидкісна гра
    application.add_handler(CallbackQueryHandler(timed_generate_variants, pattern="^timed_generate_variants"))
    application.add_handler(CallbackQueryHandler(timed_choice, pattern="^timed_choice_"))
    
    # Режим: Змагання
    application.add_handler(CallbackQueryHandler(competition_exit, pattern="^competition_exit$"))
    
    # Режим: Мультиплеєр
    application.add_handler(CallbackQueryHandler(multiplayer_guess, pattern="^mp_guess_"))
    application.add_handler(CallbackQueryHandler(multiplayer_custom_guess, pattern="^mp_custom_"))
    application.add_handler(CallbackQueryHandler(multiplayer_hint, pattern="^mp_hint_"))
    application.add_handler(CallbackQueryHandler(multiplayer_exit, pattern="^multiplayer_exit_"))
    application.add_handler(CallbackQueryHandler(multiplayer_cancel, pattern="^multiplayer_cancel_"))
    
    # Обробник текстових повідомлень
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    logger.info("✅ Бот запущено і готовий до роботи!")
    print("✅ Бот запущено! Натисніть Ctrl+C для зупинки.")
    application.run_polling()

if __name__ == "__main__":
    main()
