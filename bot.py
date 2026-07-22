import os
import telebot

TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

bot = telebot.TeleBot(TOKEN)

mensaje = """
🚨 BGM Trading Signals Bot ACTIVADO

✅ Conexión correcta
🤖 Sistema listo para recibir señales
"""

bot.send_message(CHAT_ID, mensaje)
