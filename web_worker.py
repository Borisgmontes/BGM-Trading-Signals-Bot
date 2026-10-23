import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import telebot
from signal_engine import scan

logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
log = logging.getLogger('BGM')
TOKEN = os.getenv('BOT_TOKEN', '').strip()
CHAT_ID = os.getenv('CHAT_ID', '').strip()
POLL_SECONDS = max(60, int(os.getenv('POLL_SECONDS', '300')))
ready = {'telegram_configured': bool(TOKEN and CHAT_ID), 'scanner_started': False}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/', '/health'):
            self.send_response(404); self.end_headers(); return
        body = json.dumps({'service':'BGM Trading Signals','status':'running' if ready['scanner_started'] else ('configuration_required' if not ready['telegram_configured'] else 'starting'), **ready, 'risk_pct':os.getenv('RISK_PCT','0.01'), 'trading_execution':False}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *args):
        return

def scanner():
    if not ready['telegram_configured']:
        log.error('Define BOT_TOKEN y CHAT_ID en Render; el servicio queda a la espera de configuración.')
        return
    bot = telebot.TeleBot(TOKEN)
    def send_message(message): bot.send_message(CHAT_ID, message, disable_web_page_preview=True)
    try:
        send_message('🚨 BGM Trading Signals iniciado.\nMotor Binance público activo. Riesgo configurado: ' + str(float(os.getenv('RISK_PCT','0.01'))*100) + '% por operación.\nSolo señales que cumplan todos los filtros; lo demás será NO TRADE.')
        ready['scanner_started'] = True
    except Exception:
        log.exception('No se pudo enviar mensaje inicial a Telegram.')
    while True:
        try: scan(send_message)
        except Exception: log.exception('Error general durante el escaneo.')
        time.sleep(POLL_SECONDS)

if __name__ == '__main__':
    threading.Thread(target=scanner, daemon=True).start()
    HTTPServer(('0.0.0.0', int(os.getenv('PORT','10000'))), Handler).serve_forever()
