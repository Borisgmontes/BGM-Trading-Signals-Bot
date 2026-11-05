"""Private single-owner PWA dashboard API and web-push delivery."""
import json, os, hmac, logging
from pathlib import Path
from urllib.parse import unquote
import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("BGM.dashboard")
ROOT = Path(__file__).parent / "dashboard"
PIN = os.getenv("DASHBOARD_PIN", "").strip()
VAPID_PUBLIC = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com").strip()
DEFAULT = {"timeframe":"5m","modules":["trend","rsi","macd","volume","atr","bollinger","liquidity","bos"],"min_score":3,"target_r":2.0,"enabled":True}
# Free Render has no persistent disk. This fallback keeps the dashboard usable,
# but settings/signals/subscriptions reset whenever the instance restarts.
_MEM_CONFIG = dict(DEFAULT)
_MEM_SIGNALS = []
_MEM_SUBSCRIPTIONS = {}
_MEM_NEXT_ID = 1

def _db():
    url=os.getenv("DATABASE_URL","").strip()
    if not url: raise RuntimeError("Falta DATABASE_URL: el dashboard necesita almacenamiento persistente.")
    return psycopg.connect(url,row_factory=dict_row,connect_timeout=10)

def init_dashboard_db():
    if not os.getenv("DATABASE_URL", "").strip():
        log.warning("Dashboard running in volatile memory mode; configure DATABASE_URL for persistence.")
        return
    with _db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_config (
          id SMALLINT PRIMARY KEY DEFAULT 1 CHECK(id=1), config JSONB NOT NULL, updated_at TIMESTAMPTZ DEFAULT now())""")
        conn.execute("""INSERT INTO bgm_dashboard_config(id,config) VALUES(1,%s) ON CONFLICT(id) DO NOTHING""",(json.dumps(DEFAULT),))
        conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_push (
          endpoint TEXT PRIMARY KEY, subscription JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_signals (
          id BIGSERIAL PRIMARY KEY, candle_id TEXT NOT NULL, timeframe TEXT NOT NULL, direction TEXT NOT NULL,
          entry DOUBLE PRECISION NOT NULL, stop DOUBLE PRECISION NOT NULL, target DOUBLE PRECISION NOT NULL,
          score INTEGER NOT NULL, maximum INTEGER NOT NULL, probability DOUBLE PRECISION,
          confirmations JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'CANDIDATE',
          created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(candle_id,timeframe))""")

def get_settings():
    if not os.getenv("DATABASE_URL", "").strip():
        return dict(_MEM_CONFIG)
    with _db() as conn:
        row=conn.execute("SELECT config FROM bgm_dashboard_config WHERE id=1").fetchone()
        return dict(row["config"]) if row else dict(DEFAULT)

def set_settings(config):
    modules=config.get("modules")
    if not isinstance(modules,list) or not modules or len(set(modules))!=len(modules) or not set(modules).issubset({"trend","rsi","macd","volume","atr","bollinger","liquidity","bos"}):
        raise ValueError("Selecciona al menos un indicador válido.")
    tf=config.get("timeframe")
    if tf not in ("5m","15m","1h","4h"): raise ValueError("Temporalidad no válida.")
    score=int(config.get("min_score",3))
    if not 1<=score<=len(modules): raise ValueError("Las confirmaciones mínimas no son válidas.")
    rr=float(config.get("target_r",2))
    if rr not in (1.5,2.0,3.0): raise ValueError("TP permitido: 1.5R, 2R o 3R.")
    clean={"timeframe":tf,"modules":modules,"min_score":score,"target_r":rr,"enabled":True}
    if not os.getenv("DATABASE_URL", "").strip():
        _MEM_CONFIG.clear(); _MEM_CONFIG.update(clean)
        return clean
    with _db() as conn:
        conn.execute("INSERT INTO bgm_dashboard_config(id,config,updated_at) VALUES(1,%s,now()) ON CONFLICT(id) DO UPDATE SET config=EXCLUDED.config,updated_at=now()", (json.dumps(clean),))
    return clean

def list_signals():
    if not os.getenv("DATABASE_URL", "").strip():
        return [dict(x) for x in reversed(_MEM_SIGNALS[-30:]) if x["status"] in ("CANDIDATE","CONFIRMED")]
    with _db() as conn:
        rows=conn.execute("""SELECT id,candle_id,timeframe,direction,entry,stop,target,score,maximum,probability,
          confirmations,status,created_at FROM bgm_dashboard_signals WHERE status IN ('CANDIDATE','CONFIRMED')
          ORDER BY id DESC LIMIT 30""").fetchall()
    out=[]
    for r in rows:
        d=dict(r); d["id"]=str(d["id"]); d["confirmations"]=list(d["confirmations"] or [])
        d["created_at"]=d["created_at"].isoformat() if d["created_at"] else None
        out.append(d)
    return out

def save_subscription(sub):
    endpoint=sub.get("endpoint")
    if not endpoint or not isinstance(sub.get("keys"),dict): raise ValueError("Suscripción push no válida.")
    if not os.getenv("DATABASE_URL", "").strip():
        _MEM_SUBSCRIPTIONS[endpoint] = dict(sub)
        return
    with _db() as conn:
        conn.execute("INSERT INTO bgm_dashboard_push(endpoint,subscription) VALUES(%s,%s) ON CONFLICT(endpoint) DO UPDATE SET subscription=EXCLUDED.subscription",(endpoint,json.dumps(sub)))

def update_signal(signal_id,status):
    if status not in ("CONFIRMED","DISCARDED"): raise ValueError("Estado no válido.")
    if not os.getenv("DATABASE_URL", "").strip():
        for item in _MEM_SIGNALS:
            if str(item["id"]) == str(signal_id) and item["status"] == "CANDIDATE":
                item["status"] = status
                return True
        return False
    with _db() as conn:
        cur=conn.execute("UPDATE bgm_dashboard_signals SET status=%s WHERE id=%s AND status='CANDIDATE'",(status,int(signal_id)))
        return cur.rowcount>0

def _push(signal):
    if not (VAPID_PUBLIC and VAPID_PRIVATE): return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.error("pywebpush dependency missing"); return
    if not os.getenv("DATABASE_URL", "").strip():
        rows=[{"endpoint":k,"subscription":v} for k,v in _MEM_SUBSCRIPTIONS.items()]
    else:
        with _db() as conn:
            rows=conn.execute("SELECT endpoint,subscription FROM bgm_dashboard_push").fetchall()
    probability = (" · Probabilidad " + str(signal["probability"]) + "%") if signal.get("probability") is not None else " · Probabilidad en calibración"
    payload=json.dumps({"title":"BGM · " + signal["direction"] + " BTCUSDT","body":signal["timeframe"] + probability + " · Entrada " + format(signal["entry"], ".2f") + " · TP " + format(signal["target"], ".2f") + " · SL " + format(signal["stop"], ".2f"),"url":"/","tag":"bgm-" + str(signal["id"])})
    for row in rows:
        try:
            webpush(subscription_info=dict(row["subscription"]),data=payload,vapid_private_key=VAPID_PRIVATE,
              vapid_claims={"sub":VAPID_EMAIL})
        except Exception as exc:
            log.warning("Push failed: %s",exc)
            if getattr(exc,"response",None) is not None and exc.response.status_code==410:
                with _db() as conn: conn.execute("DELETE FROM bgm_dashboard_push WHERE endpoint=%s",(row["endpoint"],))

def scan_dashboard():
    """Called by the existing scanner after startup; only closed candles are evaluated."""
    try:
        cfg=get_settings()
        from radar_engine import fetch_radar_candles,evaluate_radar,estimate_probability
        df=fetch_radar_candles("BTCUSDT",cfg["timeframe"])
        candle_id,signal=evaluate_radar(df,cfg)
        if not signal: return
        probability=estimate_probability(df,cfg,signal["direction"])
        signal["probability"] = probability
        if not os.getenv("DATABASE_URL", "").strip():
            global _MEM_NEXT_ID
            if any(x["candle_id"] == candle_id and x["timeframe"] == cfg["timeframe"] for x in _MEM_SIGNALS): return
            signal_row=dict(signal,id=str(_MEM_NEXT_ID),status="CANDIDATE",created_at=None)
            _MEM_NEXT_ID += 1
            _MEM_SIGNALS.append(signal_row)
            _push(signal_row)
            return
        with _db() as conn:
            row=conn.execute("""INSERT INTO bgm_dashboard_signals(candle_id,timeframe,direction,entry,stop,target,score,maximum,
              probability,confirmations) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(candle_id,timeframe) DO NOTHING RETURNING id""",
              (candle_id,cfg["timeframe"],signal["direction"],signal["entry"],signal["stop"],signal["target"],
               signal["score"],signal["maximum"],probability,json.dumps(signal["confirmations"]))).fetchone()
        if row:
            signal["id"]=str(row["id"]); _push(signal)
    except Exception:
        log.exception("Dashboard radar scan failed")

def _json(handler,status,data):
    body=json.dumps(data).encode()
    handler.send_response(status); handler.send_header("Content-Type","application/json; charset=utf-8")
    handler.send_header("Cache-Control","no-store"); handler.send_header("Content-Length",str(len(body)))
    handler.end_headers(); handler.wfile.write(body)

def _read(handler):
    n=int(handler.headers.get("Content-Length","0"))
    return json.loads(handler.rfile.read(n) or b"{}")

def handle(handler):
    path=unquote(handler.path.split("?",1)[0])
    if path in ("/","/dashboard.js","/dashboard.css","/manifest.json","/sw.js"):
        names={"/":"index.html","/dashboard.js":"dashboard.js","/dashboard.css":"dashboard.css","/manifest.json":"manifest.json","/sw.js":"sw.js"}
        file=ROOT/names[path]
        if not file.exists(): _json(handler,404,{"error":"Dashboard asset not found"}); return True
        body=file.read_bytes(); typ="text/html; charset=utf-8" if file.suffix==".html" else "application/javascript; charset=utf-8" if file.suffix==".js" else "text/css; charset=utf-8" if file.suffix==".css" else "application/manifest+json" if file.suffix==".json" else "application/javascript; charset=utf-8"
        handler.send_response(200); handler.send_header("Content-Type",typ); handler.send_header("Cache-Control","no-cache"); handler.send_header("Content-Length",str(len(body)))
        if path=="/sw.js": handler.send_header("Service-Worker-Allowed","/")
        handler.end_headers(); handler.wfile.write(body); return True
    if not path.startswith("/api/dashboard/"): return False
    if not PIN:
        _json(handler,503,{"error":"Falta configurar DASHBOARD_PIN en el servicio."}); return True
    if path=="/api/dashboard/login" and handler.command=="POST":
        supplied=handler.headers.get("X-Dashboard-Token","")
        if hmac.compare_digest(supplied,PIN): _json(handler,200,{"ok":True})
        else: _json(handler,401,{"error":"PIN incorrecto."})
        return True
    supplied=handler.headers.get("X-Dashboard-Token","")
    if not hmac.compare_digest(supplied,PIN): _json(handler,401,{"error":"Acceso no autorizado."}); return True
    try:
        if path=="/api/dashboard/settings" and handler.command=="GET": _json(handler,200,get_settings())
        elif path=="/api/dashboard/settings" and handler.command=="POST": _json(handler,200,set_settings(_read(handler)))
        elif path=="/api/dashboard/signals" and handler.command=="GET": _json(handler,200,{"signals":list_signals()})
        elif path=="/api/dashboard/push-key" and handler.command=="GET":
            if not VAPID_PUBLIC: raise RuntimeError("Falta configurar VAPID_PUBLIC_KEY.")
            _json(handler,200,{"public_key":VAPID_PUBLIC})
        elif path=="/api/dashboard/push-subscription" and handler.command=="POST": save_subscription(_read(handler)); _json(handler,200,{"ok":True})
        elif path.startswith("/api/dashboard/signals/") and handler.command=="POST":
            bits=path.strip("/").split("/")
            if len(bits)!=5 or bits[4] not in ("confirm","discard"): _json(handler,404,{"error":"Ruta no encontrada."})
            else:
                status="CONFIRMED" if bits[4]=="confirm" else "DISCARDED"
                _json(handler,200,{"ok":update_signal(bits[3],status)})
        else: _json(handler,404,{"error":"Ruta no encontrada."})
    except (ValueError,json.JSONDecodeError) as exc: _json(handler,400,{"error":str(exc)})
    except Exception as exc: log.exception("Dashboard API error"); _json(handler,503,{"error":"Servicio no configurado o almacenamiento no disponible."})
    return True
