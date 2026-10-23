import os
import telebot

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN:
    raise RuntimeError("Falta la variable de entorno BOT_TOKEN.")

bot = telebot.TeleBot(TOKEN)

def send_message(message: str, chat_id=None):
    destination = chat_id or CHAT_ID
    if not destination:
        raise RuntimeError("Falta la variable de entorno CHAT_ID.")
    return bot.send_message(destination, message, disable_web_page_preview=True)

if __name__ == "__main__":
    if not CHAT_ID:
        raise RuntimeError("Falta la variable de entorno CHAT_ID.")
    send_message("🚨 BGM Trading Signals Bot ACTIVADO\n\nConexión de Telegram correcta.")
