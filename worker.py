import os
import time
import logging
import telebot
from signal_engine import scan

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
POLL_SECONDS = max(60, int(os.getenv("POLL_SECONDS", "300")))

if not TOKEN or not CHAT_ID:
    raise RuntimeError("Configura BOT_TOKEN y CHAT_ID en las variables de entorno.")

bot = telebot.TeleBot(TOKEN)

def send_message(message: str):
    bot.send_message(CHAT_ID, message, disable_web_page_preview=True)

if __name__ == "__main__":
    bot.send_message(CHAT_ID, "🚨 BGM Trading Signals iniciado.\nMotor Binance público activo. Riesgo configurado: 1% por operación.\nSe enviarán únicamente señales que cumplan todos los filtros; las demás serán NO TRADE.")
    while True:
        scan(send_message)
        time.sleep(POLL_SECONDS)
