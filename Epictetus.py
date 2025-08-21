import os
import logging
import asyncio
import requests
import re
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor

# --- Загружаем переменные окружения ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise ValueError("Не найден TELEGRAM_BOT_TOKEN или OPENAI_API_KEY в .env файле")

# --- Логгирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Инициализация бота ---
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot)

# --- Папка с промтами ---
PROMPTS_DIR = "prompts"

# --- Хранилище последних сообщений пользователей ---
user_inputs = {}

# --- Загрузка списка кирпичей ---
def get_bricks() -> dict:
    bricks = {}
    for filename in os.listdir(PROMPTS_DIR):
        if filename.endswith(".txt"):
            brick_name = os.path.splitext(filename)[0]
            bricks[brick_name] = os.path.join(PROMPTS_DIR, filename)
    return bricks

# --- Загрузка промта и параметров из файла ---
def load_prompt_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    config = {
        "model": "gpt-3.5-turbo",
        "temperature": 1.0,
        "prompt": ""
    }

    prompt_lines = []
    for line in lines:
        model_match = re.match(r"#\s*model\s*:\s*(.+)", line.strip())
        temp_match = re.match(r"#\s*temperature\s*:\s*(.+)", line.strip())

        if model_match:
            config["model"] = model_match.group(1).strip()
        elif temp_match:
            try:
                config["temperature"] = float(temp_match.group(1).strip())
            except ValueError:
                pass
        else:
            prompt_lines.append(line)

    config["prompt"] = "".join(prompt_lines).strip()
    return config

# --- Синхронный запрос в GPT ---
def get_chat_completion_sync(messages, model, temperature):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature
    }
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

# --- Асинхронная обёртка GPT ---
async def query_gpt(prompt: str, model: str, temperature: float) -> str:
    loop = asyncio.get_running_loop()
    try:
        messages = [{"role": "user", "content": prompt}]
        result = await loop.run_in_executor(
            None,
            lambda: get_chat_completion_sync(messages, model=model, temperature=temperature)
        )
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        logger.exception("GPT API error:\n")
        return "Произошла ошибка при обращении к GPT API."

# --- Текст от пользователя ---
@dp.message_handler(content_types=types.ContentType.TEXT)
async def handle_text(message: types.Message):
    user_inputs[message.from_user.id] = message.text
    keyboard = InlineKeyboardMarkup()
    for brick_name in get_bricks().keys():
        keyboard.add(InlineKeyboardButton(text=brick_name, callback_data=brick_name))
    await message.reply("Выберите действие:", reply_markup=keyboard)

# --- Обработка нажатия кнопки ---
@dp.callback_query_handler()
async def handle_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    text = user_inputs.get(user_id)

    if not text:
        await callback_query.answer("Сначала отправьте текст.", show_alert=True)
        return

    brick_name = callback_query.data
    bricks = get_bricks()

    if brick_name not in bricks:
        await callback_query.answer("Неизвестная команда.", show_alert=True)
        return

    config = load_prompt_config(bricks[brick_name])
    final_prompt = config["prompt"].replace("{{input}}", text)

    await callback_query.answer("Обрабатываю...")
    response = await query_gpt(final_prompt, config["model"], config["temperature"])
    await bot.send_message(user_id, response)

# --- Запуск ---
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
