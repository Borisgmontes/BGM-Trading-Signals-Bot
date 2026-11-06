"""Private single-owner PWA dashboard API and web-push delivery."""
import json, os, hmac, logging, base64
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from radar_engine import validate_radar_config
from signal_tracker import resolve_directional_outcome
import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("BGM.dashboard")
ROOT = Path(__file__).parent / "dashboard"
PIN = os.getenv("DASHBOARD_PIN", "").strip()
VAPID_PUBLIC = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "").strip().replace("\\n", "\n")
VAPID_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com").strip()
DEFAULT = {"timeframe":"5m","modules":["trend","rsi","macd","volume","atr","bollinger","liquidity","bos"],"min_score":3,"target_r":2.0,"enabled":True}
# Free Render has no persistent disk. This fallback keeps the dashboard usable,
# but settings/signals/subscriptions reset whenever the instance restarts.
_MEM_CONFIG = dict(DEFAULT)
_MEM_SIGNALS = []
_MEM_SUBSCRIPTIONS = {}
_MEM_NEXT_ID = 1
_SCAN_STATUS = {
    "last_attempt_at": None, "last_success_at": None, "last_candle_time": None,
    "last_price": None, "candles_received": 0, "timeframe": None,
    "scan_count": 0, "success_count": 0, "last_error": None,
    "last_signal_at": None, "last_push_sent": 0, "last_push_error": None,
}

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def scan_status():
    return dict(_SCAN_STATUS)


def _load_vapid_key():
    """Load PEM or base64url VAPID private keys and verify their public pair."""
    try:
        from py_vapid import Vapid
        from cryptography.hazmat.primitives import serialization

        key_text = VAPID_PRIVATE.strip()
        if "-----BEGIN" in key_text:
            lines = [line.strip() for line in key_text.splitlines() if line.strip()]
            start = next(i for i, line in enumerate(lines) if line.startswith("-----BEGIN "))
            end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("-----END "))
            pem = "\n".join(lines[start:end + 1]) + "\n"
            vapid = Vapid.from_pem(pem.encode("utf-8"))
        else:
            vapid = Vapid.from_string(key_text)

        public_raw = vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        derived_public = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode("ascii")
        configured_public = VAPID_PUBLIC.strip().rstrip("=")
        if not configured_public or not hmac.compare_digest(derived_public, configured_public):
            raise ValueError("VAPID_PUBLIC_KEY no corresponde a VAPID_PRIVATE_KEY.")
        return vapid
    except Exception as exc:
        raise RuntimeError(
            "Clave VAPID inválida: revisa que VAPID_PRIVATE_KEY sea PEM o base64url "
            "y que corresponda a VAPID_PUBLIC_KEY."
        ) from exc

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
          confirmations JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'CANDIDATE', result TEXT, closed_at TIMESTAMPTZ,
          result_reason TEXT, last_checked_candle BIGINT, created_at TIMESTAMPTZ DEFAULT now(),
          UNIQUE(candle_id,timeframe))""")
        conn.execute("ALTER TABLE bgm_dashboard_signals ADD COLUMN IF NOT EXISTS result TEXT")
        conn.execute("ALTER TABLE bgm_dashboard_signals ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ")
        conn.execute("ALTER TABLE bgm_dashboard_signals ADD COLUMN IF NOT EXISTS result_reason TEXT")
        conn.execute("ALTER TABLE bgm_dashboard_signals ADD COLUMN IF NOT EXISTS last_checked_candle BIGINT")

def get_settings():
    if not os.getenv("DATABASE_URL", "").strip():
        return dict(_MEM_CONFIG)
    with _db() as conn:
        row=conn.execute("SELECT config FROM bgm_dashboard_config WHERE id=1").fetchone()
        return dict(row["config"]) if row else dict(DEFAULT)

def set_settings(config):
    clean = {"symbol":"BTCUSDT","timeframe":config.get("timeframe"),"modules":config.get("modules"),
             "min_score":config.get("min_score",3),"target_r":config.get("target_r",2.0),
             "enabled":bool(config.get("enabled",True))}
    validate_radar_config(clean)
    if not os.getenv("DATABASE_URL", "").strip():
        _MEM_CONFIG.clear(); _MEM_CONFIG.update(clean)
        return clean
    with _db() as conn:
        conn.execute("INSERT INTO bgm_dashboard_config(id,config,updated_at) VALUES(1,%s,now()) ON CONFLICT(id) DO UPDATE SET config=EXCLUDED.config,updated_at=now()", (json.dumps(clean),))
    return clean

def _serialize_signal(row):
    d=dict(row); d["id"]=str(d["id"]); d["confirmations"]=list(d.get("confirmations") or [])
    for key in ("created_at","closed_at"):
        if d.get(key) and hasattr(d[key],"isoformat"): d[key]=d[key].isoformat()
    return d


def list_signals():
    if not os.getenv("DATABASE_URL", "").strip():
        return [dict(x) for x in reversed(_MEM_SIGNALS) if x["status"]=="CANDIDATE"][-30:]
    with _db() as conn:
        rows=conn.execute("""SELECT id,candle_id,timeframe,direction,entry,stop,target,score,maximum,probability,
          confirmations,status,created_at FROM bgm_dashboard_signals WHERE status='CANDIDATE' ORDER BY id DESC LIMIT 30""").fetchall()
    return [_serialize_signal(r) for r in rows]


def list_trades():
    if not os.getenv("DATABASE_URL", "").strip():
        rows=[dict(x) for x in _MEM_SIGNALS if x.get("status") in ("CONFIRMED","CLOSED")]
    else:
        with _db() as conn:
            rows=conn.execute("""SELECT id,candle_id,timeframe,direction,entry,stop,target,score,maximum,probability,
              confirmations,status,result,result_reason,created_at,closed_at FROM bgm_dashboard_signals
              WHERE status IN ('CONFIRMED','CLOSED') ORDER BY id DESC LIMIT 500""").fetchall()
        rows=[_serialize_signal(r) for r in rows]
    wins=sum(x.get("result")=="WIN" for x in rows); losses=sum(x.get("result")=="LOSS" for x in rows)
    closed=wins+losses
    r_values=[float(x.get("rr") or 2.0) if x.get("result")=="WIN" else -1.0
              for x in rows if x.get("result") in ("WIN","LOSS")]
    gp=sum(v for v in r_values if v>0); gl=abs(sum(v for v in r_values if v<0))
    return {"trades":rows,"stats":{"total":len(rows),"wins":wins,"losses":losses,
      "open":sum(x.get("status")=="CONFIRMED" for x in rows),
      "win_rate":round(100*wins/closed,1) if closed else None,
      "profit_factor":round(gp/gl,2) if gl else (None if not gp else "∞"),"net_r":round(sum(r_values),2)}}


def update_trade_result(signal_id,result):
    raise ValueError("El resultado se calcula automáticamente al tocar SL o TP.")


def track_open_signals(df,timeframe):
    candles=df.to_dict("records"); closed=[]
    if not os.getenv("DATABASE_URL", "").strip():
        for item in _MEM_SIGNALS:
            if item.get("status")!="CONFIRMED" or item.get("result") or item.get("timeframe")!=timeframe: continue
            try: entry_ms=int(item["candle_id"])
            except (TypeError,ValueError): continue
            for candle in candles:
                if int(candle["open_time"])<=entry_ms: continue
                result,reason=resolve_directional_outcome(item["direction"],candle["high"],candle["low"],item["stop"],item["target"])
                if result:
                    item.update({"status":"CLOSED","result":result,"result_reason":reason,"closed_at":_utc_now()})
                    closed.append(dict(item)); break
        return closed
    with _db() as conn:
        rows=conn.execute("""SELECT id,candle_id,direction,stop,target,last_checked_candle
          FROM bgm_dashboard_signals WHERE status='CONFIRMED' AND result IS NULL AND timeframe=%s ORDER BY id""",(timeframe,)).fetchall()
        for row in rows:
            try: entry_ms=int(row["candle_id"])
            except (TypeError,ValueError): continue
            last_checked=int(row["last_checked_candle"] or entry_ms)
            for candle in candles:
                candle_ms=int(candle["open_time"])
                if candle_ms<=max(entry_ms,last_checked): continue
                result,reason=resolve_directional_outcome(row["direction"],candle["high"],candle["low"],row["stop"],row["target"])
                if result:
                    updated=conn.execute("""UPDATE bgm_dashboard_signals SET status='CLOSED',result=%s,result_reason=%s,
                      closed_at=now(),last_checked_candle=%s WHERE id=%s AND status='CONFIRMED' AND result IS NULL
                      RETURNING id,result,result_reason""",(result,reason,candle_ms,row["id"])).fetchone()
                    if updated: closed.append(dict(updated))
                    break
                last_checked=candle_ms
            conn.execute("""UPDATE bgm_dashboard_signals SET last_checked_candle=%s
              WHERE id=%s AND status='CONFIRMED' AND result IS NULL""",(last_checked,row["id"]))
    return closed


def update_signal(signal_id,status):
    if status not in ("CONFIRMED","DISCARDED"): raise ValueError("Estado no válido.")
    if not os.getenv("DATABASE_URL", "").strip():
        for item in _MEM_SIGNALS:
            if str(item["id"])==str(signal_id) and item["status"]=="CANDIDATE":
                item["status"]=status; item["confirmed_at"]=_utc_now() if status=="CONFIRMED" else None
                return True
        return False
    with _db() as conn:
        cur=conn.execute("UPDATE bgm_dashboard_signals SET status=%s WHERE id=%s AND status='CANDIDATE'",(status,int(signal_id)))
        return cur.rowcount>0

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
    if not (VAPID_PUBLIC and VAPID_PRIVATE):
        _SCAN_STATUS["last_push_error"] = "Faltan claves VAPID."
        return 0
    sent = 0
    try:
        from pywebpush import webpush
        vapid_key = _load_vapid_key()
    except ImportError:
        log.error("pywebpush dependency missing")
        _SCAN_STATUS["last_push_error"] = "Falta la dependencia pywebpush."
        return 0
    except RuntimeError as exc:
        _SCAN_STATUS["last_push_error"] = str(exc)
        log.error("Push configuration invalid: %s", exc)
        return 0
    if not os.getenv("DATABASE_URL", "").strip():
        rows=[{"endpoint":k,"subscription":v} for k,v in _MEM_SUBSCRIPTIONS.items()]
    else:
        with _db() as conn:
            rows=conn.execute("SELECT endpoint,subscription FROM bgm_dashboard_push").fetchall()
    probability = (" · Probabilidad " + str(signal["probability"]) + "%") if signal.get("probability") is not None else " · Probabilidad en calibración"
    if signal.get("test"):
        payload=json.dumps({"title":"BGM · Prueba de notificación","body":"Las notificaciones emergentes están funcionando en este Android.","url":"/","tag":"bgm-push-test"})
    else:
        payload=json.dumps({"title":"BGM · " + signal["direction"] + " BTCUSDT","body":signal["timeframe"] + probability + " · Entrada " + format(signal["entry"], ".2f") + " · TP " + format(signal["target"], ".2f") + " · SL " + format(signal["stop"], ".2f"),"url":"/","tag":"bgm-" + str(signal["id"])})
    errors = []
    for row in rows:
        try:
            webpush(subscription_info=dict(row["subscription"]),data=payload,vapid_private_key=vapid_key,
              vapid_claims={"sub":VAPID_EMAIL})
            sent += 1
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc)[:240])
            log.warning("Push delivery failed (%s): %s", type(exc).__name__, str(exc)[:240])
            if getattr(exc,"response",None) is not None and exc.response.status_code==410:
                if not os.getenv("DATABASE_URL", "").strip():
                    _MEM_SUBSCRIPTIONS.pop(row["endpoint"], None)
                else:
                    with _db() as conn: conn.execute("DELETE FROM bgm_dashboard_push WHERE endpoint=%s",(row["endpoint"],))
    _SCAN_STATUS["last_push_sent"] = sent
    _SCAN_STATUS["last_push_error"] = "; ".join(errors[:2]) if errors else None
    log.info("Push delivery complete: sent=%s subscriptions=%s errors=%s", sent, len(rows), len(errors))
    return sent

def send_test_push():
    test={"id":"test","direction":"LONG","timeframe":"5m","probability":None,
          "entry":100000.0,"target":102000.0,"stop":99000.0,"test":True}
    sent=_push(test)
    if not sent:
        raise RuntimeError("No hay suscripción Push válida o faltan claves VAPID.")
    return sent

def scan_dashboard():
    """Fetch and evaluate the latest closed BTC candle; expose verifiable health."""
    _SCAN_STATUS["last_attempt_at"] = _utc_now()
    _SCAN_STATUS["scan_count"] += 1
    _SCAN_STATUS["last_error"] = None
    try:
        cfg=get_settings()
        _SCAN_STATUS["timeframe"] = cfg["timeframe"]
        from radar_engine import fetch_radar_candles,evaluate_radar,estimate_probability
        df=fetch_radar_candles("BTCUSDT",cfg["timeframe"])
        if df is None or len(df) < 205:
            raise ValueError("El proveedor devolvió menos de 205 velas utilizables.")
        last=df.iloc[-1]
        candle_ms=int(last["open_time"])
        candle_time=datetime.fromtimestamp(candle_ms/1000,timezone.utc).isoformat()
        price=float(last["close"])
        _SCAN_STATUS.update({
            "last_success_at": _utc_now(), "last_candle_time": candle_time,
            "last_price": price, "candles_received": int(len(df)),
            "success_count": _SCAN_STATUS["success_count"] + 1,
            "last_error": None,
        })
        track_open_signals(df,cfg["timeframe"])
        candle_id,signal=evaluate_radar(df,cfg)
        if not signal:
            log.info("Dashboard scan OK: symbol=BTCUSDT tf=%s candles=%s candle=%s price=%.2f signal=none",
                     cfg["timeframe"],len(df),candle_time,price)
            return
        probability=estimate_probability(df,cfg,signal["direction"])
        signal["probability"] = probability
        if not os.getenv("DATABASE_URL", "").strip():
            global _MEM_NEXT_ID
            if any(x["candle_id"] == candle_id and x["timeframe"] == cfg["timeframe"] for x in _MEM_SIGNALS):
                log.info("Dashboard scan OK: symbol=BTCUSDT tf=%s candles=%s price=%.2f signal=duplicate",
                         cfg["timeframe"],len(df),price)
                return
            signal_row=dict(signal,id=str(_MEM_NEXT_ID),status="CANDIDATE",created_at=_utc_now(),result=None,closed_at=None)
            _MEM_NEXT_ID += 1
            _MEM_SIGNALS.append(signal_row)
            _SCAN_STATUS["last_signal_at"] = _utc_now()
            _push(signal_row)
            log.info("Dashboard scan OK: symbol=BTCUSDT tf=%s candles=%s candle=%s price=%.2f signal=%s probability=%s",
                     cfg["timeframe"],len(df),candle_time,price,signal["direction"],probability)
            return
        with _db() as conn:
            row=conn.execute("""INSERT INTO bgm_dashboard_signals(candle_id,timeframe,direction,entry,stop,target,score,maximum,
              probability,confirmations,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
              ON CONFLICT(candle_id,timeframe) DO NOTHING RETURNING id""",
              (candle_id,cfg["timeframe"],signal["direction"],signal["entry"],signal["stop"],signal["target"],
               signal["score"],signal["maximum"],probability,json.dumps(signal["confirmations"]))).fetchone()
        if row:
            signal["id"]=str(row["id"])
            _SCAN_STATUS["last_signal_at"] = _utc_now()
            _push(signal)
        log.info("Dashboard scan OK: symbol=BTCUSDT tf=%s candles=%s candle=%s price=%.2f signal=%s probability=%s new=%s",
                 cfg["timeframe"],len(df),candle_time,price,signal["direction"],probability,bool(row))
    except Exception as exc:
        _SCAN_STATUS["last_error"] = type(exc).__name__ + ": " + str(exc)[:300]
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
        elif path=="/api/dashboard/trades" and handler.command=="GET": _json(handler,200,list_trades())
        elif path=="/api/dashboard/status" and handler.command=="GET":
            _json(handler,200,{"scan":scan_status(),"persistence_mode":"postgresql" if os.getenv("DATABASE_URL","").strip() else "memory_volatile"})
        elif path=="/api/dashboard/push-key" and handler.command=="GET":
            if not VAPID_PUBLIC: raise RuntimeError("Falta configurar VAPID_PUBLIC_KEY.")
            _json(handler,200,{"public_key":VAPID_PUBLIC})
        elif path=="/api/dashboard/push-subscription" and handler.command=="POST": save_subscription(_read(handler)); _json(handler,200,{"ok":True})
        elif path=="/api/dashboard/push-test" and handler.command=="POST": _json(handler,200,{"sent":send_test_push()})
        elif path.startswith("/api/dashboard/trades/") and handler.command=="POST":
            bits=path.strip("/").split("/")
            if len(bits)!=5 or bits[4]!="result": _json(handler,404,{"error":"Ruta no encontrada."})
            else: _json(handler,200,{"ok":update_trade_result(bits[3],_read(handler).get("result"))})
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
