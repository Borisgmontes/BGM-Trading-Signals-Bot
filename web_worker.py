import json, logging, os, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
import telebot
from telebot import types
import user_store
import dashboard_api
from strategy_engine import validate_config, fetch_candles, evaluate, format_alert
from radar_engine import validate_radar_config, fetch_radar_candles, evaluate_radar, format_radar_alert, estimate_probability_details, qualifies_by_historical_probability

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("BGM")
TOKEN=os.getenv("BOT_TOKEN","").strip()
POLL_SECONDS=max(60,int(os.getenv("POLL_SECONDS","300")))
bot=telebot.TeleBot(TOKEN) if TOKEN else None
ready={"telegram_configured":bool(TOKEN),"database_configured":bool(os.getenv("DATABASE_URL")),"persistence_mode":"postgresql" if os.getenv("DATABASE_URL") else "memory_volatile","scanner_started":False,"users_seen":0}
db_ready=False
WIZARDS={}
ASSETS=[("BTC","BTCUSDT"),("ETH","ETHUSDT"),("SOL","SOLUSDT"),("BNB","BNBUSDT"),("XRP","XRPUSDT"),("ADA","ADAUSDT"),("DOGE","DOGEUSDT")]
TFS=[("5 minutos","5m"),("15 minutos","15m"),("1 hora","1h"),("4 horas","4h")]
ENTRIES=[("Ruptura","breakout"),("Cruce EMA 20/50","ema_cross"),("Barrido de liquidez","liquidity_sweep"),("Cambio de estructura","bos")]
TRENDS=[("Sin filtro","none"),("Precio vs EMA 200","ema200"),("EMA 20/50/200 alineadas","ema_alignment")]
CONFIRMS=[("Sin confirmación extra","none"),("Volumen","volume"),("Rango/ATR","atr")]
STOPS=[("ATR (dinámico)","atr"),("Último swing","swing"),("Porcentaje fijo 0,5%","fixed_pct")]
TARGETS=[("1,5R","1.5"),("2R","2.0"),("3R","3.0")]
RISKS=[("0,25%","0.25"),("0,5%","0.5"),("1%","1.0"),("2%","2.0")]
STEPS=[("symbol","Elige el activo",ASSETS),("timeframe","Elige la temporalidad",TFS),("entry","Elige el tipo de entrada",ENTRIES),("trend","Filtro de tendencia",TRENDS),("confirmation","Confirmación adicional",CONFIRMS),("stop","Cómo calcular el Stop Loss",STOPS),("target_r","Objetivo de beneficio",TARGETS),("risk_pct","Riesgo nominal por operación",RISKS)]
RADAR_MODULES=[("Tendencia EMA","trend"),("RSI","rsi"),("MACD","macd"),("Volumen","volume"),("ATR","atr"),("Bandas Bollinger","bollinger"),("Barrido de liquidez","liquidity"),("BOS","bos"),("ADX","adx"),("VWAP","vwap"),("OBV","obv"),("Stochastic","stochastic"),("Supertrend","supertrend"),("Divergencias RSI","divergence"),("Fibonacci","fibonacci"),("Patrones chartistas","chart_patterns"),("Fair Value Gaps","fvg"),("Order Blocks","order_blocks"),("Fakeouts","fakeout")]
RADAR_TFS=[("5 minutos","5m"),("15 minutos","15m"),("1 hora","1h"),("4 horas","4h")]

HELP="""🤖 BGM TRADING SIGNALS
Usa los botones para configurar una estrategia sin escribir parámetros.

 /start — abrir menú
 /menu — configurar o administrar estrategias
 /list — ver tus estrategias
 /test — alerta simulada

Elige activo, temporalidad, entrada, filtros, stop, objetivo y riesgo. Al guardar, el escáner revisará datos públicos de mercado y enviará una alerta cuando coincidan las reglas. No ejecuta órdenes ni garantiza rentabilidad."""

def private(m): return bool(m.chat.type=="private" and m.from_user and not m.from_user.is_bot)
def say(m,t,**kw): bot.send_message(m.chat.id,t,disable_web_page_preview=True,**kw)
def main_keyboard():
    k=types.InlineKeyboardMarkup(row_width=2)
    k.add(types.InlineKeyboardButton("➕ Crear estrategia",callback_data="wizard:start"),
          types.InlineKeyboardButton("📋 Mis estrategias",callback_data="strategies:list"))
    k.add(types.InlineKeyboardButton("📡 Configurar BTC RADAR",callback_data="radar:start"))
    k.add(types.InlineKeyboardButton("🧪 Probar formato",callback_data="test:sim"))
    k.add(types.InlineKeyboardButton("❔ Ayuda",callback_data="help:show"))
    return k
def register(m):
    if not private(m): return say(m,"Abre un chat privado con el bot y escribe /start.")
    try:
        user_store.upsert_user(m.from_user.id,m.chat.id,m.from_user.username)
        say(m,"✅ BGM listo. Configura tus alertas con los botones de abajo.",reply_markup=main_keyboard())
    except Exception:
        log.exception("register failed"); say(m,"No pude registrar el chat. Revisa la conexión de almacenamiento del bot.")
def show_step(chat_id,uid,edit_message_id=None):
    w=WIZARDS.get(uid)
    if not w: return bot.send_message(chat_id,"Abre el menú para empezar.",reply_markup=main_keyboard())
    idx=w["step"]
    if idx>=len(STEPS):
        cfg=w["config"]
        text=("🧾 RESUMEN DE TU ESTRATEGIA\n\n"
          f"Activo: {cfg['symbol']}\nTemporalidad: {cfg['timeframe']}\nEntrada: {dict(ENTRIES).get(cfg['entry'])}\n"
          f"Tendencia: {dict(TRENDS).get(cfg['trend'])}\nConfirmación: {dict(CONFIRMS).get(cfg['confirmation'])}\n"
          f"Stop: {dict(STOPS).get(cfg['stop'])}\nObjetivo: {cfg['target_r']}R\nRiesgo nominal: {cfg['risk_pct']}%\n\n"
          "Guarda para activar el escaneo de alertas.")
        kb=types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("💾 Guardar y activar",callback_data="wizard:save"),
               types.InlineKeyboardButton("↩️ Empezar de nuevo",callback_data="wizard:restart"))
        kb.add(types.InlineKeyboardButton("❌ Cancelar",callback_data="wizard:cancel"))
    else:
        key,title,options=STEPS[idx]
        text=f"⚙️ CONFIGURAR ESTRATEGIA ({idx+1}/{len(STEPS)})\n\n{title}:"
        kb=types.InlineKeyboardMarkup(row_width=2)
        buttons=[]
        for label,value in options:
            buttons.append(types.InlineKeyboardButton(label,callback_data=f"wizard:set:{key}:{value}"))
        kb.add(*buttons)
        nav=[]
        if idx>0: nav.append(types.InlineKeyboardButton("⬅️ Atrás",callback_data="wizard:back"))
        nav.append(types.InlineKeyboardButton("✖️ Cancelar",callback_data="wizard:cancel"))
        kb.row(*nav)
    if edit_message_id:
        try: bot.edit_message_text(text,chat_id,edit_message_id,reply_markup=kb)
        except Exception: bot.send_message(chat_id,text,reply_markup=kb)
    else: bot.send_message(chat_id,text,reply_markup=kb)

def show_radar_step(chat_id,uid,edit_message_id=None):
    w=WIZARDS.get(uid)
    if not w or not w.get("radar"): return
    cfg=w["config"]; step=w["step"]
    kb=types.InlineKeyboardMarkup(row_width=2)
    if step==0:
        text="📡 BTC RADAR (1/4)\n\nSelecciona temporalidad:"
        for label,value in RADAR_TFS:
            kb.add(types.InlineKeyboardButton(label,callback_data=f"radar:set:timeframe:{value}"))
    elif step==1:
        text="📡 BTC RADAR (2/4)\n\nActiva o desactiva indicadores. Seleccionados: "+str(len(cfg["modules"]))
        for label,value in RADAR_MODULES:
            mark="☑️" if value in cfg["modules"] else "⬜"
            kb.add(types.InlineKeyboardButton(mark+" "+label,callback_data=f"radar:toggle:{value}"))
        kb.add(types.InlineKeyboardButton("Continuar ➡️",callback_data="radar:continue"))
    elif step==2:
        text="📡 BTC RADAR (3/4)\n\n¿Cuántas confirmaciones mínimas deben coincidir?"
        for n in range(1,len(cfg["modules"])+1):
            kb.add(types.InlineKeyboardButton(str(n)+" confirmaciones",callback_data=f"radar:set:min_score:{n}"))
    elif step==3:
        text="📡 BTC RADAR (4/4)\n\nSelecciona objetivo teórico:"
        for label,value in TARGETS:
            kb.add(types.InlineKeyboardButton(label,callback_data=f"radar:set:target_r:{value}"))
    else:
        names=dict(RADAR_MODULES)
        chosen=", ".join(names[x] for x in cfg["modules"])
        text=("🧾 RESUMEN BTC RADAR\n\nActivo: BTCUSDT\nTemporalidad: "+cfg["timeframe"]+
              "\nIndicadores: "+chosen+"\nConfirmaciones mínimas: "+str(cfg["min_score"])+
              "\nObjetivo teórico: "+str(cfg["target_r"])+"R\n\nGuardar y activar el radar?")
        kb.add(types.InlineKeyboardButton("💾 Guardar y activar",callback_data="radar:save"))
    kb.add(types.InlineKeyboardButton("✖️ Cancelar",callback_data="wizard:cancel"))
    if edit_message_id:
        try: bot.edit_message_text(text,chat_id,edit_message_id,reply_markup=kb)
        except Exception: bot.send_message(chat_id,text,reply_markup=kb)
    else: bot.send_message(chat_id,text,reply_markup=kb)

def list_for_user(chat_id,uid):
    rows=user_store.list_strategies(uid)
    if not rows: return bot.send_message(chat_id,"Todavía no tienes estrategias guardadas.",reply_markup=main_keyboard())
    kb=types.InlineKeyboardMarkup(row_width=2)
    lines=["📋 TUS ESTRATEGIAS"]
    for x in rows:
        cfg=x["config"]; cfg=json.loads(cfg) if isinstance(cfg,str) else cfg
        if cfg.get("mode")=="radar":
            details=f"BTCUSDT {cfg['timeframe']} · BTC RADAR · {len(cfg['modules'])} indicadores · {cfg['min_score']} confirmaciones · TP {cfg['target_r']}R"
        else:
            details=f"{cfg['symbol']} {cfg['timeframe']} · {cfg['entry']} · TP {cfg['target_r']}R · riesgo {cfg['risk_pct']}%"
        lines.append(f"\nID {x['id']} · {x['name']} · {'🟢 ACTIVA' if x['enabled'] else '⏸ PAUSADA'}\n{details}")
        if x["enabled"]:
            kb.add(types.InlineKeyboardButton(f"⏸ Pausar {x['id']}",callback_data=f"strategy:off:{x['id']}"))
        else:
            kb.add(types.InlineKeyboardButton(f"🟢 Activar {x['id']}",callback_data=f"strategy:on:{x['id']}"))
        kb.add(types.InlineKeyboardButton(f"🗑 Borrar {x['id']}",callback_data=f"strategy:delete:{x['id']}"))
    kb.add(types.InlineKeyboardButton("➕ Nueva estrategia",callback_data="wizard:start"),
           types.InlineKeyboardButton("🏠 Menú",callback_data="menu:show"))
    bot.send_message(chat_id,"\n".join(lines),reply_markup=kb,disable_web_page_preview=True)

if bot:
    @bot.message_handler(commands=["start","menu"])
    def start_handler(m): register(m)
    @bot.message_handler(commands=["help"])
    def help_handler(m):
        if private(m): say(m,HELP,reply_markup=main_keyboard())
    @bot.message_handler(commands=["list"])
    def list_handler(m):
        if private(m):
            try: list_for_user(m.chat.id,m.from_user.id)
            except Exception: log.exception("list failed"); say(m,"No pude consultar tus estrategias. Comprueba el almacenamiento.")
    @bot.message_handler(commands=["test"])
    def test_handler(m):
        if private(m): say(m,"🧪 ALERTA DE PRUEBA — SIMULADA\nBTCUSDT LONG\nEntrada, SL y TP ficticios. No es una señal real.",reply_markup=main_keyboard())

    @bot.callback_query_handler(func=lambda c: True)
    def callback_handler(c):
        if not c.from_user or c.from_user.is_bot: return
        uid=c.from_user.id; chat_id=c.message.chat.id if c.message else uid
        try:
            if c.message and c.message.chat.type!="private":
                bot.answer_callback_query(c.id,"Abre el chat privado con BGM."); return
            user_store.upsert_user(uid,chat_id,c.from_user.username)
            data=c.data or ""
            bot.answer_callback_query(c.id)
            if data=="strategies:list":
                list_for_user(chat_id,uid); return
            if data in ("menu:show","help:show"):
                bot.send_message(chat_id,HELP if data=="help:show" else "¿Qué quieres hacer?",reply_markup=main_keyboard()); return
            if data=="test:sim":
                bot.send_message(chat_id,"🧪 ALERTA DE PRUEBA — SIMULADA\nBTCUSDT LONG\nEntrada, SL y TP ficticios. No es señal real de mercado.",reply_markup=main_keyboard()); return
            if data=="radar:start":
                WIZARDS[uid]={"radar":True,"step":0,"config":{"symbol":"BTCUSDT","modules":[x[1] for x in RADAR_MODULES],"target_r":2.0}}
                show_radar_step(chat_id,uid,c.message.message_id); return
            if data.startswith("radar:"):
                w=WIZARDS.get(uid)
                if not w or not w.get("radar"):
                    bot.send_message(chat_id,"Inicia BTC RADAR desde el menú."); return
                if data.startswith("radar:toggle:"):
                    module=data.split(":")[-1]
                    if module in w["config"]["modules"]: w["config"]["modules"].remove(module)
                    else: w["config"]["modules"].append(module)
                    show_radar_step(chat_id,uid,c.message.message_id); return
                if data=="radar:continue":
                    if not w["config"]["modules"]:
                        bot.send_message(chat_id,"Activa al menos un indicador."); return
                    w["step"]=2; show_radar_step(chat_id,uid,c.message.message_id); return
                if data.startswith("radar:set:"):
                    _,_,key,value=data.split(":",3)
                    if key=="timeframe": w["config"][key]=value; w["step"]=1
                    elif key=="min_score": w["config"][key]=int(value); w["step"]=3
                    elif key=="target_r": w["config"][key]=float(value); w["step"]=4
                    show_radar_step(chat_id,uid,c.message.message_id); return
                if data=="radar:save":
                    cfg=dict(w["config"]); cfg["mode"]="radar"; cfg["name"]="BTC_RADAR_"+cfg["timeframe"]
                    validate_radar_config(cfg)
                    existing={x["name"] for x in user_store.list_strategies(uid)}
                    base=cfg["name"]; suffix=2
                    while cfg["name"] in existing:
                        cfg["name"]=base+"_"+str(suffix); suffix+=1
                    sid=user_store.create_strategy(uid,cfg["name"],cfg)
                    WIZARDS.pop(uid,None)
                    bot.send_message(chat_id,f"✅ BTC RADAR guardado y activado (ID {sid}).\nAnalizará velas cerradas y enviará alertas cuando se alcance el mínimo de confluencias.",reply_markup=main_keyboard()); return
            if data=="wizard:start" or data=="wizard:restart":
                WIZARDS[uid]={"step":0,"config":{}}
                show_step(chat_id,uid,c.message.message_id); return
            if data=="wizard:cancel":
                WIZARDS.pop(uid,None); bot.send_message(chat_id,"Configuración cancelada.",reply_markup=main_keyboard()); return
            if data=="wizard:back":
                w=WIZARDS.get(uid)
                if w:
                    w["step"]=max(0,w["step"]-1)
                    for key,_,_ in STEPS[w["step"]+1:]: w["config"].pop(key,None)
                    show_step(chat_id,uid,c.message.message_id)
                return
            if data.startswith("wizard:set:"):
                w=WIZARDS.get(uid)
                if not w: bot.send_message(chat_id,"La sesión de configuración expiró. Pulsa Crear estrategia.",reply_markup=main_keyboard()); return
                _,_,key,value=data.split(":",3)
                expected=STEPS[w["step"]][0]
                if key!=expected: bot.send_message(chat_id,"Pulsa una opción del menú actual."); return
                if key=="target_r": value=float(value)
                elif key=="risk_pct": value=float(value)
                w["config"][key]=value; w["step"]+=1
                show_step(chat_id,uid,c.message.message_id); return
            if data=="wizard:save":
                w=WIZARDS.get(uid)
                if not w or w["step"]<len(STEPS): bot.send_message(chat_id,"Completa la configuración desde Crear estrategia."); return
                cfg=dict(w["config"])
                base_name=f"{cfg['symbol']}_{cfg['timeframe']}_{cfg['entry']}"
                existing={x["name"] for x in user_store.list_strategies(uid)}
                cfg["name"]=base_name
                suffix=2
                while cfg["name"] in existing:
                    cfg["name"]=f"{base_name}_{suffix}"; suffix+=1
                validate_config(cfg)
                sid=user_store.create_strategy(uid,cfg["name"],cfg)
                WIZARDS.pop(uid,None)
                bot.send_message(chat_id,f"✅ Estrategia guardada y activada (ID {sid}).\nEl bot revisará el mercado y enviará alertas cuando las reglas coincidan. No hay garantía de que aparezcan señales.",reply_markup=main_keyboard())
                return
            if data.startswith("strategy:"):
                _,action,sid_s=data.split(":"); sid=int(sid_s)
                if action in ("on","off"):
                    ok=user_store.set_strategy_enabled(uid,sid,action=="on")
                    bot.send_message(chat_id,("🟢 Estrategia activada." if action=="on" else "⏸ Estrategia pausada.") if ok else "No existe una estrategia tuya con ese ID.")
                elif action=="delete":
                    ok=user_store.delete_strategy(uid,sid)
                    bot.send_message(chat_id,"🗑 Estrategia eliminada." if ok else "No existe una estrategia tuya con ese ID.")
                list_for_user(chat_id,uid); return
        except ValueError as e:
            log.warning("callback validation failed: %s",e); bot.send_message(chat_id,"No se pudo guardar: "+str(e))
        except Exception:
            log.exception("callback handler failed"); bot.send_message(chat_id,"Ocurrió un error al procesar esa opción. Inténtalo de nuevo.")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if dashboard_api.handle(self): return
        if self.path!="/health": self.send_response(404); self.end_headers(); return
        scan=dashboard_api.scan_status()
        healthy=bool(scan.get("last_success_at") and not scan.get("last_error"))
        body=json.dumps({"service":"BGM Trading Signals","status":"scanning" if healthy else ("starting" if ready["scanner_started"] and db_ready else "configuration_required"),"scanner_thread_started":ready["scanner_started"],"database_ready":db_ready,"last_scan_ok":healthy,"last_scan_at":scan.get("last_success_at"),"last_scan_error":scan.get("last_error"),"scan_count":scan.get("scan_count",0),"persistence_mode":ready["persistence_mode"],"telegram_configured":ready["telegram_configured"],"database_configured":ready["database_configured"],"users_seen":ready["users_seen"],"trading_execution":False}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if dashboard_api.handle(self): return
        self.send_response(404); self.end_headers()
    def log_message(self,*args): pass

def scanner():
    global db_ready
    if not bot: log.warning("BOT_TOKEN missing; dashboard-only mode")
    while True:
        try:
            if not db_ready:
                user_store.init_db()
                dashboard_api.init_dashboard_db()
                db_ready=True
                log.info("Storage schema ready; mode=%s",ready["persistence_mode"])
            dashboard_api.scan_dashboard()
            strategies=user_store.get_active_strategies() if bot else []
            ready["users_seen"]=len({x["telegram_user_id"] for x in strategies})
            grouped={}
            for row in strategies:
                cfg=row["config"]; cfg=json.loads(cfg) if isinstance(cfg,str) else cfg
                cfg["name"]=row["name"]; mode=cfg.get("mode","strategy")
                grouped.setdefault((cfg.get("symbol","BTCUSDT"),cfg["timeframe"],mode),[]).append((row,cfg))
            for (symbol,timeframe,mode),items in grouped.items():
                try:
                    df=fetch_radar_candles(symbol,timeframe) if mode=="radar" else fetch_candles(symbol,timeframe)
                except Exception: log.exception("Market data failed %s %s",symbol,timeframe); continue
                for row,cfg in items:
                    try:
                        if mode=="radar":
                            cid,sig=evaluate_radar(df,cfg)
                            formatter=format_radar_alert
                            if sig is not None:
                                probability_stats=estimate_probability_details(df,cfg,sig["direction"])
                                if not qualifies_by_historical_probability(probability_stats):
                                    log.info("Telegram radar candidate filtered: strategy=%s direction=%s probability=%s samples=%s minimum_strictly_above=35%%",
                                             row["name"],sig["direction"],probability_stats["probability"],probability_stats["samples"])
                                    continue
                                sig["probability"]=probability_stats["probability"]
                                sig["probability_samples"]=probability_stats["samples"]
                        else:
                            cid,sig=evaluate(df,cfg)
                            formatter=format_alert
                        if cid is None or sig is None or not user_store.claim_signal(row["id"],cid): continue
                        sig["strategy_name"]=row["name"]
                        try:
                            if bot: bot.send_message(row["chat_id"],formatter(sig),disable_web_page_preview=True)
                        except Exception:
                            user_store.release_signal(row["id"],cid)
                            raise
                    except Exception: log.exception("Strategy failed id=%s",row["id"])
        except Exception: log.exception("Scanner cycle failed")
        time.sleep(POLL_SECONDS)
def listener():
    while True:
        try: bot.infinity_polling(timeout=20,long_polling_timeout=15,skip_pending=True)
        except Exception: log.exception("Telegram polling failed"); time.sleep(5)
if __name__=="__main__":
    log.info("Starting BGM menu bot; persistence_mode=%s; telegram_configured=%s",ready["persistence_mode"],ready["telegram_configured"])
    if bot: threading.Thread(target=listener,daemon=True).start()
    ready["scanner_started"]=True
    threading.Thread(target=scanner,daemon=True).start()
    HTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
