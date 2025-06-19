from flask import Flask, request
import asyncio
import os

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Update
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties

from main import dp  # dp уже содержит все хендлеры

TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)
session = AiohttpSession()

bot = Bot(
    token=TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.model_validate_json(request.data)
    asyncio.run(dp.feed_update(bot=bot, update=update))
    return "ok", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    from asyncio import get_event_loop
    try:
        loop = get_event_loop()
        if loop.is_closed():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        url = os.getenv("WEBHOOK_URL")
        loop.run_until_complete(_set_webhook(url))
        return f"Webhook установлен на {url}", 200
    except Exception as e:
        return f"Ошибка при установке webhook: {e}", 500


async def _set_webhook(url):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url)
