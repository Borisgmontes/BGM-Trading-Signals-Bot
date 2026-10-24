import json, logging, os, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
import telebot
import user_store
from strategy_engine import validate_config, fetch_candles, evaluate, format_alert

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("BGM")
TOKEN=os.getenv("BOT_TOKEN","").strip()
POLL_SECONDS=max(60,int(os.getenv("POLL_SECONDS","300")))
bot=telebot.TeleBot(TOKEN) if TOKEN else None
ready={"telegram_configured":bool(TOKEN),"database_configured":bool(os.getenv("DATABASE_URL")),"scanner_started":False,"users_seen":0}
db_ready=False
HELP="""🤖 BGM MULTIUSUARIO
/start — registrar tu chat privado
/help — ayuda
/new NOMBRE ACTIVO TF ENTRADA TENDENCIA CONFIRMACION STOP OBJETIVO_R RIESGO_PCT
Ejemplo:
/new BTC_Ruptura BTCUSDT 5m breakout ema200 volume atr 2 0.5
/list — tus subestrategias
/on ID — activar una tuya
/off ID — pausar una tuya
/delete ID — borrar una tuya
/test — alerta simulada

Entrada: breakout, ema_cross, liquidity_sweep, bos
Tendencia: none, ema200, ema_alignment
Confirmación: none, volume, atr
Stop: atr, swing, fixed_pct
TF: 5m, 15m, 1h, 4h
Riesgo nominal: 0.25, 0.5, 1 o 2%; objetivo: 1.5, 2 o 3R.
Chat privado únicamente. El bot no ejecuta órdenes ni garantiza rentabilidad."""

def private(m): return bool(m.chat.type=="private" and m.from_user and not m.from_user.is_bot)
def say(m,t): bot.send_message(m.chat.id,t,disable_web_page_preview=True)
def register(m):
    if not private(m): return say(m,"Abre un chat privado con el bot y escribe /start.")
    try:
        user_store.upsert_user(m.from_user.id,m.chat.id,m.from_user.username)
        say(m,"✅ Chat privado registrado. Tus estrategias y alertas son independientes.\n\n"+HELP)
    except Exception:
        log.exception("register failed"); say(m,"No pude guardar el usuario. El administrador debe configurar DATABASE_URL de PostgreSQL persistente en Render.")
def new(m):
    if not private(m): return
    try:
        user_store.upsert_user(m.from_user.id,m.chat.id,m.from_user.username)
        p=(m.text or "").split()
        if len(p)!=10: return say(m,"Formato:\n/new NOMBRE ACTIVO TF ENTRADA TENDENCIA CONFIRMACION STOP OBJETIVO_R RIESGO_PCT\nEjemplo:\n/new BTC_Ruptura BTCUSDT 5m breakout ema200 volume atr 2 0.5")
        _,name,sym,tf,entry,trend,confirm,stop,rr,risk=p
        if len(name)>32 or not name.replace("_","").replace("-","").isalnum(): return say(m,"Nombre inválido: máximo 32 caracteres y solo letras, números, guion o guion bajo.")
        cfg={"name":name,"symbol":sym.upper(),"timeframe":tf.lower(),"entry":entry.lower(),"trend":trend.lower(),"confirmation":confirm.lower(),"stop":stop.lower(),"target_r":float(rr),"risk_pct":float(risk)}
        validate_config(cfg); sid=user_store.create_strategy(m.from_user.id,name,cfg)
        say(m,f"✅ Guardada y activa: ID {sid} — {name}\n{cfg['symbol']} {cfg['timeframe']} | {cfg['entry']} | tendencia {cfg['trend']} | confirmación {cfg['confirmation']}\nStop {cfg['stop']} | TP {cfg['target_r']}R | riesgo nominal {cfg['risk_pct']}%.\n/list para consultar.")
    except ValueError as e: say(m,"Configuración rechazada: "+str(e))
    except Exception: log.exception("create strategy failed"); say(m,"No pude guardar la estrategia. Revisa DATABASE_URL y PostgreSQL.")
def listing(m):
    if not private(m): return
    try:
        user_store.upsert_user(m.from_user.id,m.chat.id,m.from_user.username)
        rows=user_store.list_strategies(m.from_user.id)
        if not rows: return say(m,"No tienes subestrategias. Usa /help.")
        out=["📋 TUS SUBESTRATEGIAS"]
        for x in rows:
            cfg=x["config"]; cfg=json.loads(cfg) if isinstance(cfg,str) else cfg
            out.append(f"\nID {x['id']} — {x['name']} — {'🟢 ACTIVA' if x['enabled'] else '⏸ PAUSADA'}\n{cfg['symbol']} {cfg['timeframe']} | {cfg['entry']} | tendencia {cfg['trend']} | confirmación {cfg['confirmation']} | SL {cfg['stop']} | TP {cfg['target_r']}R | riesgo {cfg['risk_pct']}%")
        say(m,"\n".join(out))
    except Exception: log.exception("listing failed"); say(m,"Error consultando la base de datos.")
def toggle(m,on):
    if not private(m): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit(): return say(m,"Formato: /"+("on" if on else "off")+" ID")
    try: say(m,("✅ Activada." if on else "⏸ Pausada.") if user_store.set_strategy_enabled(m.from_user.id,int(p[1]),on) else "No existe una subestrategia tuya con ese ID.")
    except Exception: log.exception("toggle failed"); say(m,"Error de base de datos.")
def delete(m):
    if not private(m): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit(): return say(m,"Formato: /delete ID")
    try: say(m,"🗑 Eliminada." if user_store.delete_strategy(m.from_user.id,int(p[1])) else "No existe una subestrategia tuya con ese ID.")
    except Exception: log.exception("delete failed"); say(m,"Error de base de datos.")
def test(m):
    if private(m): say(m,"🧪 ALERTA DE PRUEBA — SIMULADA\nBTCUSDT LONG\nEntrada, SL y TP ficticios. No es señal de mercado.")
if bot:
    bot.message_handler(commands=["start"])(register)
    bot.message_handler(commands=["help"])(lambda m:say(m,HELP) if private(m) else None)
    bot.message_handler(commands=["new"])(new)
    bot.message_handler(commands=["list"])(listing)
    bot.message_handler(commands=["on"])(lambda m:toggle(m,True))
    bot.message_handler(commands=["off"])(lambda m:toggle(m,False))
    bot.message_handler(commands=["delete"])(delete)
    bot.message_handler(commands=["test"])(test)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/","/health"): self.send_response(404); self.end_headers(); return
        body=json.dumps({"service":"BGM Trading Signals","status":"running" if ready["scanner_started"] and db_ready else "configuration_required",**ready,"trading_execution":False}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass

def scanner():
    global db_ready
    if not bot: log.error("BOT_TOKEN missing"); return
    while True:
        try:
            if not db_ready: user_store.init_db(); db_ready=True; log.info("PostgreSQL schema ready")
            strategies=user_store.get_active_strategies()
            ready["users_seen"]=len({x["telegram_user_id"] for x in strategies})
            grouped={}
            for row in strategies:
                cfg=row["config"]; cfg=json.loads(cfg) if isinstance(cfg,str) else cfg
                cfg["name"]=row["name"]; grouped.setdefault((cfg["symbol"],cfg["timeframe"]),[]).append((row,cfg))
            for key,items in grouped.items():
                try: df=fetch_candles(*key)
                except Exception: log.exception("Market data failed %s %s",*key); continue
                for row,cfg in items:
                    try:
                        cid,sig=evaluate(df,cfg)
                        if cid is None or sig is None or not user_store.claim_signal(row["id"],cid): continue
                        sig["strategy_name"]=row["name"]
                        bot.send_message(row["chat_id"],format_alert(sig),disable_web_page_preview=True)
                    except Exception: log.exception("Strategy failed id=%s",row["id"])
        except Exception: log.exception("Scanner cycle failed")
        time.sleep(POLL_SECONDS)
def listener():
    while True:
        try: bot.infinity_polling(timeout=20,long_polling_timeout=15,skip_pending=True)
        except Exception: log.exception("Telegram polling failed"); time.sleep(5)
if __name__=="__main__":
    if bot: threading.Thread(target=listener,daemon=True).start()
    threading.Thread(target=scanner,daemon=True).start()
    HTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
