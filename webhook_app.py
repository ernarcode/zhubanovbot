from flask import Flask, request
import asyncio
import os

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Update
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties

from main import dp  # все хендлеры зарегистрированы в main.py

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = Flask(__name__)
session = AiohttpSession()

bot = Bot(
    token=TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# 👇 Асинхронная обёртка для обработки обновлений
async def handle_update(update: Update):
    await dp.feed_update(bot=bot, update=update)

@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.model_validate_json(request.data)
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(handle_update(update))
    return "ok", 200 

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    loop = asyncio.get_event_loop()
    try:
        result = loop.run_until_complete(_set_webhook(WEBHOOK_URL))
        return f"Webhook установлен на {WEBHOOK_URL}", 200
    except Exception as e:
        return f"Ошибка при установке webhook: {e}", 500

async def _set_webhook(url):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url)
