import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import telebot
from signal_engine import scan

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("BGM")
TOKEN = os.getenv("BOT_TOKEN", "").strip()
POLL_SECONDS = max(60, int(os.getenv("POLL_SECONDS", "300")))
bot = telebot.TeleBot(TOKEN) if TOKEN else None
destination_lock = threading.Lock()
destination = {"chat_id": None}
ready = {"telegram_configured": bool(TOKEN), "destination_configured": False, "scanner_started": False}

def register_chat(message):
    if not message.from_user or message.from_user.is_bot:
        return
    chat_id = message.chat.id
    with destination_lock:
        destination["chat_id"] = chat_id
        ready["destination_configured"] = True
    try:
        bot.send_message(chat_id, "✅ BGM Trading Signals conectado correctamente.\n"
            f"Chat ID registrado: {chat_id}\n"
            "Recibirás alertas cuando se cumplan los filtros. Si no hay setup válido, indicará NO TRADE.\n"
            f"Riesgo configurado: {float(os.getenv('RISK_PCT', '0.01')) * 100:.2f}% por operación.")
        log.info("Telegram destination registered from user interaction.")
    except Exception:
        log.exception("Could not confirm Telegram destination.")

def test_alert(message):
    if not message.from_user or message.from_user.is_bot:
        return
    chat_id = message.chat.id
    with destination_lock:
        destination["chat_id"] = chat_id
        ready["destination_configured"] = True
    sample = (
        "🧪 BGM TRADING SIGNALS — ALERTA DE PRUEBA\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Activo: BTCUSDT\n"
        "Dirección: LONG (SIMULADA)\n"
        "Entrada: 67,000.00 (FICTICIA)\n"
        "Stop Loss: 66,700.00 (FICTICIO)\n"
        "Take Profit: 67,600.00 (FICTICIO)\n"
        "Riesgo nominal: 1%\n"
        "Estado: DEMOSTRACIÓN — NO OPERAR\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Esta alerta comprueba el envío por Telegram. No es una señal de mercado ni usa precios actuales."
    )
    try:
        bot.send_message(chat_id, sample, disable_web_page_preview=True)
        log.info("Telegram test alert sent successfully.")
    except Exception:
        log.exception("Could not send Telegram test alert.")

if bot:
    bot.message_handler(commands=["start", "id"])(register_chat)
    bot.message_handler(commands=["test"])(test_alert)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health"):
            self.send_response(404); self.end_headers(); return
        with destination_lock:
            dest_ready = bool(destination["chat_id"])
        status = "running" if ready["scanner_started"] and dest_ready else ("waiting_for_telegram_start" if TOKEN and not dest_ready else "configuration_required")
        body = json.dumps({"service":"BGM Trading Signals","status":status,**ready,"risk_pct":os.getenv("RISK_PCT","0.01"),"trading_execution":False}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *args):
        return

def send_message(message):
    with destination_lock:
        chat_id = destination["chat_id"]
    if not chat_id:
        log.info("Waiting for a human Telegram chat to send /start.")
        return
    try:
        bot.send_message(chat_id, message, disable_web_page_preview=True)
    except Exception:
        log.exception("Telegram send failed.")

def telegram_listener():
    if not bot:
        log.error("BOT_TOKEN is missing; Telegram listener cannot start.")
        return
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=15, skip_pending=True)
        except Exception:
            log.exception("Telegram polling failed; retrying.")
            time.sleep(5)

def scanner():
    if not bot:
        log.error("Define BOT_TOKEN in Render environment variables.")
        return
    ready["scanner_started"] = True
    log.info("BGM scanner started; waiting for Telegram /start to register destination.")
    while True:
        try:
            scan(send_message)
        except Exception:
            log.exception("General scanning error.")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    if bot:
        threading.Thread(target=telegram_listener, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", "10000"))), Handler).serve_forever()
