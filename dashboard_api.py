"""Multi-user PWA dashboard API and web-push delivery."""
import json, os, hmac, logging, base64, hashlib, contextvars, uuid, secrets
from concurrent.futures import ThreadPoolExecutor
from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from radar_engine import validate_radar_config, qualifies_by_historical_probability, DEFAULT_INDICATOR_PARAMS
from signal_tracker import resolve_directional_outcome
import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("BGM.dashboard")
ROOT = Path(__file__).parent / "dashboard"
_TENANT = contextvars.ContextVar("bgm_dashboard_tenant", default="__anonymous__")
VAPID_PUBLIC = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "").strip().replace("\\n", "\n")
VAPID_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com").strip()
DEFAULT = {"symbol":"BTCUSDT","timeframe":"5m","higher_timeframe":"none","modules":["trend","rsi","macd","volume","atr","bollinger","liquidity","bos"],"min_score":3,"target_r":2.0,"enabled":True,"indicator_params":dict(DEFAULT_INDICATOR_PARAMS)}
# Free Render has no persistent disk. This fallback keeps the dashboard usable,
# but settings/signals/subscriptions reset whenever the instance restarts.
_MEM_CONFIG = dict(DEFAULT)
_MEM_SIGNALS = []
_MEM_SUBSCRIPTIONS = {}
_MEM_NEXT_ID = 1
_MEM_STATS_EPOCH = {}
_SCAN_STATUS_TEMPLATE = {
    "last_attempt_at": None, "last_success_at": None, "last_candle_time": None,
    "last_price": None, "candles_received": 0, "timeframe": None,
    "scan_count": 0, "success_count": 0, "last_error": None,
    "last_signal_at": None, "last_push_sent": 0, "last_push_error": None,
}
_SCAN_STATUS_BY_TENANT = {}


class _TenantStatus(MutableMapping):
    """Context-local scan telemetry so one PIN cannot view another user's status."""
    def _state(self):
        return _SCAN_STATUS_BY_TENANT.setdefault(_TENANT.get(), dict(_SCAN_STATUS_TEMPLATE))
    def __getitem__(self, key): return self._state()[key]
    def __setitem__(self, key, value): self._state()[key] = value
    def __delitem__(self, key): del self._state()[key]
    def __iter__(self): return iter(self._state())
    def __len__(self): return len(self._state())


_SCAN_STATUS = _TenantStatus()

def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def strategy_hash(config):
    relevant = {"symbol": config.get("symbol", "BTCUSDT"),
                "timeframe": config.get("timeframe"),
                "higher_timeframe": config.get("higher_timeframe", "none"),
                "modules": sorted(config.get("modules") or []),
                "min_score": int(config.get("min_score", 3)),
                "target_r": float(config.get("target_r", 2.0)),
                "indicator_params": config.get("indicator_params") or DEFAULT_INDICATOR_PARAMS}
    raw = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _current_epoch(config_hash):
    if not os.getenv("DATABASE_URL", "").strip():
        return int(_MEM_STATS_EPOCH.get(config_hash, 0))
    with _db() as conn:
        row = conn.execute("SELECT epoch FROM bgm_dashboard_strategy_state WHERE strategy_hash=%s",
                           (config_hash,)).fetchone()
        return int(row["epoch"]) if row else 0

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
    if not url: raise RuntimeError("Falta DATABASE_URL: el dashboard multiusuario necesita PostgreSQL persistente.")
    conn=psycopg.connect(url,row_factory=dict_row,connect_timeout=10)
    conn.execute("SELECT set_config('app.user_id',%s,false)",(_TENANT.get(),))
    return conn


def _pin_digest(pin, salt):
    return hashlib.pbkdf2_hmac("sha256",pin.encode("utf-8"),bytes.fromhex(salt),310000).hex()


def _tenant_scope(user_id):
    class Scope:
        def __enter__(self): self.token=_TENANT.set(str(user_id)); return self
        def __exit__(self,*args): _TENANT.reset(self.token)
    return Scope()


def _provision_pins(conn):
    pins=[x.strip() for x in os.getenv("DASHBOARD_PINS","").split(",") if x.strip()]
    if not pins: log.warning("DASHBOARD_PINS is empty; no dashboard PINs provisioned."); return
    for pin in pins:
        if not pin.isdigit() or len(pin)<8: raise ValueError("Cada PIN debe contener al menos 8 dígitos.")
        users=conn.execute("SELECT pin_salt,pin_hash FROM bgm_dashboard_users").fetchall()
        if any(hmac.compare_digest(_pin_digest(pin,u["pin_salt"]),u["pin_hash"]) for u in users): continue
        salt=secrets.token_hex(16)
        conn.execute("INSERT INTO bgm_dashboard_users(user_id,pin_salt,pin_hash,active) VALUES(%s,%s,%s,true)",
                     (str(uuid.uuid4()),salt,_pin_digest(pin,salt)))


def _user_for_pin(pin):
    if not pin or not pin.isdigit(): return None
    with _tenant_scope("__auth__"):
        with _db() as conn:
            users=conn.execute("SELECT user_id,pin_salt,pin_hash FROM bgm_dashboard_users WHERE active=true").fetchall()
            for user in users:
                if hmac.compare_digest(_pin_digest(pin,user["pin_salt"]),user["pin_hash"]):
                    return user["user_id"]
    return None


def _user_for_session(token):
    if not token: return None
    digest=hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _tenant_scope("__auth__"):
        with _db() as conn:
            row=conn.execute("SELECT user_id FROM bgm_dashboard_sessions WHERE token_hash=%s AND expires_at>now()",
                             (digest,)).fetchone()
            return row["user_id"] if row else None


def _create_session(user_id):
    token=secrets.token_urlsafe(32)
    digest=hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _tenant_scope("__auth__"):
        with _db() as conn:
            conn.execute("INSERT INTO bgm_dashboard_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,now()+interval '30 days')",
                         (digest,user_id))
    return token

def _verify_four_user_concurrency(users):
    """Exercise four isolated account configs concurrently, then restore each snapshot."""
    selected = users[:4]
    if len(selected) < 4:
        raise RuntimeError("La prueba multiusuario requiere al menos cuatro cuentas PIN.")
    markers = [1.5, 2.0, 3.0, 1.5]
    snapshots = {}

    def probe(pair):
        user, marker = pair
        uid = user["user_id"]
        with _tenant_scope(uid):
            before = get_settings()
            changed = dict(before)
            changed["target_r"] = marker
            set_settings(changed)
            after = get_settings()
            if float(after["target_r"]) != marker:
                raise RuntimeError("La configuración concurrente no persistió para su usuario.")
            return uid, before

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for uid, before in pool.map(probe, zip(selected, markers)):
                snapshots[uid] = before
        def verify(pair):
            user, marker = pair
            with _tenant_scope(user["user_id"]):
                return float(get_settings()["target_r"]) == marker
        with ThreadPoolExecutor(max_workers=4) as pool:
            if not all(pool.map(verify, zip(selected, markers))):
                raise RuntimeError("Se detectó cruce de configuración entre usuarios.")
    finally:
        def restore(pair):
            uid, config = pair
            with _tenant_scope(uid):
                set_settings(config)
        if snapshots:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(restore, snapshots.items()))

    tokens = [_create_session(user["user_id"]) for user in selected]
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            owners = list(pool.map(_user_for_session, tokens))
        if owners != [user["user_id"] for user in selected]:
            raise RuntimeError("Las sesiones concurrentes no conservan su identidad.")
    finally:
        digests = [hashlib.sha256(token.encode("utf-8")).hexdigest() for token in tokens]
        with _tenant_scope("__auth__"):
            with _db() as conn:
                conn.executemany("DELETE FROM bgm_dashboard_sessions WHERE token_hash=%s",
                                 [(digest,) for digest in digests])
    log.info("Dashboard concurrency probe passed; concurrent_users=4; tenant_settings_isolated=true; sessions_isolated=true")


def init_dashboard_db():
    if not os.getenv("DATABASE_URL", "").strip():
        raise RuntimeError("DATABASE_URL es obligatorio: no se permite modo memoria en el dashboard multiusuario.")
    with _tenant_scope("__system__"):
        with _db() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_users (
              user_id TEXT PRIMARY KEY, pin_salt TEXT NOT NULL, pin_hash TEXT NOT NULL UNIQUE,
              active BOOLEAN NOT NULL DEFAULT true, created_at TIMESTAMPTZ DEFAULT now())""")
            conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_sessions (
              token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES bgm_dashboard_users(user_id) ON DELETE CASCADE,
              expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ DEFAULT now())""")
            conn.execute("CREATE INDEX IF NOT EXISTS bgm_dashboard_sessions_user_idx ON bgm_dashboard_sessions(user_id)")
            conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_config (
              id SMALLINT NOT NULL DEFAULT 1, config JSONB NOT NULL, updated_at TIMESTAMPTZ DEFAULT now(), user_id TEXT)""")
            conn.execute("ALTER TABLE bgm_dashboard_config ADD COLUMN IF NOT EXISTS user_id TEXT")
            conn.execute("ALTER TABLE bgm_dashboard_config DISABLE ROW LEVEL SECURITY")
            conn.execute("DELETE FROM bgm_dashboard_config WHERE user_id IS NULL")
            conn.execute("ALTER TABLE bgm_dashboard_config DROP CONSTRAINT IF EXISTS bgm_dashboard_config_id_check")
            conn.execute("ALTER TABLE bgm_dashboard_config DROP CONSTRAINT IF EXISTS bgm_dashboard_config_pkey")
            conn.execute("ALTER TABLE bgm_dashboard_config ALTER COLUMN user_id SET NOT NULL")
            conn.execute("ALTER TABLE bgm_dashboard_config ADD CONSTRAINT bgm_dashboard_config_pkey PRIMARY KEY(id,user_id)")
            conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_push (
              endpoint TEXT NOT NULL, subscription JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT now(), user_id TEXT)""")
            conn.execute("ALTER TABLE bgm_dashboard_push ADD COLUMN IF NOT EXISTS user_id TEXT")
            conn.execute("ALTER TABLE bgm_dashboard_push DISABLE ROW LEVEL SECURITY")
            conn.execute("DELETE FROM bgm_dashboard_push WHERE user_id IS NULL")
            conn.execute("ALTER TABLE bgm_dashboard_push DROP CONSTRAINT IF EXISTS bgm_dashboard_push_pkey")
            conn.execute("ALTER TABLE bgm_dashboard_push ALTER COLUMN user_id SET NOT NULL")
            conn.execute("ALTER TABLE bgm_dashboard_push ADD CONSTRAINT bgm_dashboard_push_pkey PRIMARY KEY(user_id,endpoint)")
            conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_signals (
              id BIGSERIAL PRIMARY KEY, candle_id TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT 'BTCUSDT', timeframe TEXT NOT NULL, direction TEXT NOT NULL,
              entry DOUBLE PRECISION NOT NULL, stop DOUBLE PRECISION NOT NULL, target DOUBLE PRECISION NOT NULL,
              score INTEGER NOT NULL, maximum INTEGER NOT NULL, probability DOUBLE PRECISION, probability_samples INTEGER, probability_wins INTEGER,
              probability_ci_low DOUBLE PRECISION, probability_ci_high DOUBLE PRECISION,
              confirmations JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'CANDIDATE', result TEXT, closed_at TIMESTAMPTZ,
              result_reason TEXT, last_checked_candle BIGINT, created_at TIMESTAMPTZ DEFAULT now(),
              UNIQUE(candle_id,timeframe))""")
            for col,typ in (("symbol","TEXT NOT NULL DEFAULT 'BTCUSDT'"),("result","TEXT"),("exit_price","DOUBLE PRECISION"),("closed_at","TIMESTAMPTZ"),
                ("result_reason","TEXT"),("last_checked_candle","BIGINT"),("probability_samples","INTEGER"),
                ("probability_wins","INTEGER"),("probability_ci_low","DOUBLE PRECISION"),("probability_ci_high","DOUBLE PRECISION"),
                ("strategy_hash","TEXT"),("config_snapshot","JSONB"),("stats_epoch","INTEGER NOT NULL DEFAULT 0"),("user_id","TEXT")):
                conn.execute(f"ALTER TABLE bgm_dashboard_signals ADD COLUMN IF NOT EXISTS {col} {typ}")
            conn.execute("ALTER TABLE bgm_dashboard_signals DISABLE ROW LEVEL SECURITY")
            conn.execute("DELETE FROM bgm_dashboard_signals WHERE user_id IS NULL")
            conn.execute("ALTER TABLE bgm_dashboard_signals ALTER COLUMN user_id SET NOT NULL")
            conn.execute("ALTER TABLE bgm_dashboard_signals DROP CONSTRAINT IF EXISTS bgm_dashboard_signals_candle_id_timeframe_key")
            conn.execute("DROP INDEX IF EXISTS bgm_dashboard_signals_candle_tf_strategy_uq")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS bgm_dashboard_signals_tenant_candle_uq ON bgm_dashboard_signals(user_id,candle_id,timeframe,strategy_hash)")
            conn.execute("""CREATE TABLE IF NOT EXISTS bgm_dashboard_strategy_state (
              strategy_hash TEXT NOT NULL, epoch INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ DEFAULT now(), user_id TEXT)""")
            conn.execute("ALTER TABLE bgm_dashboard_strategy_state ADD COLUMN IF NOT EXISTS user_id TEXT")
            conn.execute("ALTER TABLE bgm_dashboard_strategy_state DISABLE ROW LEVEL SECURITY")
            conn.execute("DELETE FROM bgm_dashboard_strategy_state WHERE user_id IS NULL")
            conn.execute("ALTER TABLE bgm_dashboard_strategy_state DROP CONSTRAINT IF EXISTS bgm_dashboard_strategy_state_pkey")
            conn.execute("ALTER TABLE bgm_dashboard_strategy_state ALTER COLUMN user_id SET NOT NULL")
            conn.execute("ALTER TABLE bgm_dashboard_strategy_state ADD CONSTRAINT bgm_dashboard_strategy_state_pkey PRIMARY KEY(strategy_hash,user_id)")
            for table in ("bgm_dashboard_config","bgm_dashboard_push","bgm_dashboard_signals","bgm_dashboard_strategy_state"):
                policy=table+"_tenant_policy"
                conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
                conn.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
                conn.execute(f"CREATE POLICY {policy} ON {table} USING (user_id=current_setting('app.user_id',true)) WITH CHECK (user_id=current_setting('app.user_id',true))")
            conn.execute("CREATE OR REPLACE FUNCTION bgm_dashboard_tenant_ids() RETURNS TABLE(user_id TEXT) LANGUAGE sql SECURITY DEFINER SET search_path=public AS 'SELECT u.user_id FROM bgm_dashboard_users AS u WHERE u.active=true'")
            _provision_pins(conn)
            users=conn.execute("SELECT user_id FROM bgm_dashboard_users WHERE active=true").fetchall()
            for user in users:
                conn.execute("SELECT set_config('app.user_id',%s,false)",(user["user_id"],))
                conn.execute("INSERT INTO bgm_dashboard_config(id,user_id,config) VALUES(1,%s,%s) ON CONFLICT(id,user_id) DO NOTHING",
                             (user["user_id"],json.dumps(DEFAULT)))
            conn.execute("SELECT set_config('app.user_id','__system__',false)")
    for user in users:
        with _tenant_scope(user["user_id"]):
            with _db() as tenant_conn:
                visible=tenant_conn.execute("SELECT count(*) AS n FROM bgm_dashboard_config").fetchone()["n"]
                if int(visible)!=1:
                    raise RuntimeError("Fallo de aislamiento RLS en la configuración de un usuario.")
    _verify_four_user_concurrency(users)
    pins=[x.strip() for x in os.getenv("DASHBOARD_PINS","").split(",") if x.strip()]
    if pins:
        test_uid=_user_for_pin(pins[0])
        if not test_uid: raise RuntimeError("La verificación del PIN de acceso falló.")
        test_token=_create_session(test_uid)
        if _user_for_session(test_token)!=test_uid:
            raise RuntimeError("La verificación de sesiones multiusuario falló.")
        digest=hashlib.sha256(test_token.encode("utf-8")).hexdigest()
        with _tenant_scope("__auth__"):
            with _db() as auth_conn: auth_conn.execute("DELETE FROM bgm_dashboard_sessions WHERE token_hash=%s",(digest,))
    log.info("Dashboard multiuser schema ready; accounts=%s; tenant_isolation=verified; pin_session=verified",len(users))


def get_settings():
    if not os.getenv("DATABASE_URL", "").strip():
        return dict(_MEM_CONFIG)
    with _db() as conn:
        row=conn.execute("SELECT config FROM bgm_dashboard_config WHERE id=1").fetchone()
        return dict(row["config"]) if row else dict(DEFAULT)

def set_settings(config):
    clean = {"symbol":config.get("symbol","BTCUSDT"),"timeframe":config.get("timeframe"),
             "higher_timeframe":config.get("higher_timeframe","none"),
             "modules":config.get("modules"),"min_score":config.get("min_score",3),
             "target_r":config.get("target_r",2.0),"enabled":bool(config.get("enabled",True)),
             "indicator_params":config.get("indicator_params") or dict(DEFAULT_INDICATOR_PARAMS)}
    validate_radar_config(clean)
    if not os.getenv("DATABASE_URL", "").strip():
        _MEM_CONFIG.clear(); _MEM_CONFIG.update(clean)
        return clean
    with _db() as conn:
        conn.execute("INSERT INTO bgm_dashboard_config(id,user_id,config,updated_at) VALUES(1,%s,%s,now()) ON CONFLICT(id,user_id) DO UPDATE SET config=EXCLUDED.config,updated_at=now()", (_TENANT.get(),json.dumps(clean)))
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
        rows=conn.execute("""SELECT id,candle_id,symbol,timeframe,direction,entry,stop,target,score,maximum,probability,
          probability_samples,probability_wins,probability_ci_low,probability_ci_high,
          confirmations,status,created_at FROM bgm_dashboard_signals WHERE status='CANDIDATE' ORDER BY id DESC LIMIT 30""").fetchall()
    return [_serialize_signal(r) for r in rows]


def list_trades():
    cfg = get_settings()
    active_hash = strategy_hash(cfg)
    epoch = _current_epoch(active_hash)
    if not os.getenv("DATABASE_URL", "").strip():
        all_rows = [dict(x) for x in _MEM_SIGNALS if x.get("status") in ("CONFIRMED", "CLOSED")]
        # Compatibility for in-memory records created before strategy tagging was added.
        for item in all_rows:
            item.setdefault("strategy_hash", active_hash)
            item.setdefault("stats_epoch", 0)
            item.setdefault("config_snapshot", cfg)
    else:
        with _db() as conn:
            rows = conn.execute("""SELECT id,candle_id,symbol,timeframe,direction,entry,stop,target,score,maximum,probability,
              probability_samples,probability_wins,probability_ci_low,probability_ci_high,
              confirmations,status,result,result_reason,exit_price,created_at,closed_at,strategy_hash,config_snapshot,stats_epoch
              FROM bgm_dashboard_signals WHERE status IN ('CONFIRMED','CLOSED') ORDER BY id DESC LIMIT 2000""").fetchall()
        all_rows = [_serialize_signal(r) for r in rows]

    def summarize(rows):
        wins = sum(x.get("result") == "WIN" for x in rows)
        losses = sum(x.get("result") == "LOSS" for x in rows)
        closed = wins + losses
        r_values = []
        for x in rows:
            if x.get("result") not in ("WIN", "LOSS"):
                continue
            risk = abs(float(x["entry"]) - float(x["stop"]))
            reward = abs(float(x["target"]) - float(x["entry"]))
            exit_price = x.get("exit_price")
            if exit_price is not None and risk:
                direction_sign = 1.0 if x.get("direction") == "LONG" else -1.0
                multiple = direction_sign * (float(exit_price) - float(x["entry"])) / risk
            else:
                multiple = reward / risk if risk else 0.0
                if x["result"] != "WIN":
                    multiple = -1.0
            r_values.append(multiple)
        gross_profit = sum(v for v in r_values if v > 0)
        gross_loss = abs(sum(v for v in r_values if v < 0))
        equity = peak = max_drawdown = 0.0
        for value in r_values:
            equity += value
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        win_values = [v for v in r_values if v > 0]
        loss_values = [v for v in r_values if v < 0]
        return {
            "total": len(rows), "wins": wins, "losses": losses,
            "open": sum(x.get("status") in ("CANDIDATE", "CONFIRMED", "OPEN") for x in rows),
            "win_rate": round(100 * wins / closed, 1) if closed else None,
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (None if not gross_profit else "∞"),
            "net_r": round(sum(r_values), 2),
            "expectancy_r": round(sum(r_values) / closed, 3) if closed else None,
            "average_win_r": round(sum(win_values) / len(win_values), 3) if win_values else None,
            "average_loss_r": round(sum(loss_values) / len(loss_values), 3) if loss_values else None,
            "max_drawdown_r": round(max_drawdown, 2),
            "closed": closed,
        }

    current = [x for x in all_rows if x.get("strategy_hash") == active_hash and int(x.get("stats_epoch", 0)) == epoch]
    grouped = {}
    for row in all_rows:
        grouped.setdefault(row.get("strategy_hash") or "legacy", []).append(row)
    grouped.setdefault(active_hash, [])
    strategies = []
    for key, rows in grouped.items():
        snapshot = (rows[0].get("config_snapshot") or {}) if rows else cfg
        strategies.append({"strategy_hash": key, "config": snapshot,
                           "stats": summarize(rows), "is_current": key == active_hash})
    strategies.sort(key=lambda x: (not x["is_current"], -x["stats"]["total"]))
    return {"trades": current[-500:], "stats": summarize(current),
            "strategy_hash": active_hash, "stats_epoch": epoch, "strategies": strategies}


def update_trade_result(signal_id,result):
    raise ValueError("El resultado se calcula automáticamente al tocar SL o TP.")


def open_signal_markets():
    if not os.getenv("DATABASE_URL", "").strip():
        return sorted({(x.get("symbol", "BTCUSDT"), x.get("timeframe")) for x in _MEM_SIGNALS
                       if x.get("status") in ("CANDIDATE","CONFIRMED") and not x.get("result")})
    with _db() as conn:
        rows=conn.execute("SELECT DISTINCT symbol,timeframe FROM bgm_dashboard_signals WHERE status IN ('CANDIDATE','CONFIRMED') AND result IS NULL").fetchall()
    return [(r["symbol"], r["timeframe"]) for r in rows]


def track_open_signals(df,timeframe,symbol="BTCUSDT"):
    """Keep signals open indefinitely; close only when TP or SL is reached."""
    candles=df.to_dict("records")
    closed=[]
    if timeframe not in ("5m","15m","1h","4h"):
        raise ValueError("Temporalidad no válida para seguimiento.")

    def outcome_for(item,candle,entry_ms):
        result,reason=resolve_directional_outcome(
            item["direction"],candle["high"],candle["low"],item["stop"],item["target"]
        )
        candle_ms=int(candle["open_time"])
        if result == "WIN":
            exit_price = float(item["target"])
        elif result == "LOSS":
            exit_price = float(item["stop"])
        else:
            return None,None,None
        return result,reason,exit_price

    if not os.getenv("DATABASE_URL", "").strip():
        for item in _MEM_SIGNALS:
            if item.get("status") not in ("CANDIDATE","CONFIRMED") or item.get("result") or item.get("timeframe")!=timeframe or item.get("symbol","BTCUSDT")!=symbol:
                continue
            try:
                entry_ms=int(item["candle_id"])
            except (TypeError,ValueError):
                continue
            last_checked=int(item.get("last_checked_candle") or entry_ms)
            for candle in candles:
                candle_ms=int(candle["open_time"])
                if candle_ms<=max(entry_ms,last_checked):
                    continue
                result,reason,exit_price=outcome_for(item,candle,entry_ms)
                item["last_checked_candle"]=candle_ms
                if result:
                    item.update({"status":"CLOSED","result":result,"result_reason":reason,
                                 "exit_price":exit_price,"closed_at":_utc_now()})
                    closed.append(dict(item))
                    break
        return closed

    with _db() as conn:
        rows=conn.execute("""SELECT id,candle_id,direction,stop,target,last_checked_candle
          FROM bgm_dashboard_signals WHERE status IN ('CANDIDATE','CONFIRMED') AND result IS NULL AND timeframe=%s AND symbol=%s ORDER BY id""",(timeframe,symbol)).fetchall()
        for row in rows:
            try:
                entry_ms=int(row["candle_id"])
            except (TypeError,ValueError):
                continue
            last_checked=int(row["last_checked_candle"] or entry_ms)
            for candle in candles:
                candle_ms=int(candle["open_time"])
                if candle_ms<=max(entry_ms,last_checked):
                    continue
                result,reason,exit_price=outcome_for(row,candle,entry_ms)
                if result:
                    updated=conn.execute("""UPDATE bgm_dashboard_signals SET status='CLOSED',result=%s,result_reason=%s,
                      exit_price=%s,closed_at=now(),last_checked_candle=%s
                      WHERE id=%s AND status IN ('CANDIDATE','CONFIRMED') AND result IS NULL
                      RETURNING id,result,result_reason,exit_price""",(result,reason,exit_price,candle_ms,row["id"])).fetchone()
                    if updated:
                        closed.append(dict(updated))
                    break
                last_checked=candle_ms
            conn.execute("""UPDATE bgm_dashboard_signals SET last_checked_candle=%s
              WHERE id=%s AND status IN ('CANDIDATE','CONFIRMED') AND result IS NULL""",(last_checked,row["id"]))
    return closed

def update_signal(signal_id,status):
    if status not in ("CONFIRMED","DISCARDED"): raise ValueError("Estado no válido.")
    if not os.getenv("DATABASE_URL", "").strip():
        for item in _MEM_SIGNALS:
            if str(item["id"]) == str(signal_id) and item["status"] == "CANDIDATE":
                item["status"] = status
                item["confirmed_at"] = _utc_now() if status == "CONFIRMED" else None
                if status == "CONFIRMED":
                    key = item.get("strategy_hash")
                    if key:
                        item["stats_epoch"] = _current_epoch(key)
                return True
        return False
    with _db() as conn:
        row = conn.execute("""SELECT strategy_hash FROM bgm_dashboard_signals
          WHERE id=%s AND status='CANDIDATE'""", (int(signal_id),)).fetchone()
        if not row:
            return False
        epoch = 0
        if status == "CONFIRMED" and row["strategy_hash"]:
            state = conn.execute("SELECT epoch FROM bgm_dashboard_strategy_state WHERE strategy_hash=%s",
                                 (row["strategy_hash"],)).fetchone()
            epoch = int(state["epoch"]) if state else 0
        cur = conn.execute("""UPDATE bgm_dashboard_signals SET status=%s,stats_epoch=%s
          WHERE id=%s AND status='CANDIDATE'""", (status, epoch, int(signal_id)))
        return cur.rowcount > 0

def save_subscription(sub):
    endpoint=sub.get("endpoint")
    if not endpoint or not isinstance(sub.get("keys"),dict): raise ValueError("Suscripción push no válida.")
    if not os.getenv("DATABASE_URL", "").strip():
        _MEM_SUBSCRIPTIONS[endpoint] = dict(sub)
        return
    with _db() as conn:
        conn.execute("INSERT INTO bgm_dashboard_push(user_id,endpoint,subscription) VALUES(%s,%s,%s) ON CONFLICT(user_id,endpoint) DO UPDATE SET subscription=EXCLUDED.subscription",(_TENANT.get(),endpoint,json.dumps(sub)))

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

def _scan_dashboard_for_tenant():
    """Fetch and evaluate the latest closed BTC candle for the current tenant."""
    _SCAN_STATUS["last_attempt_at"] = _utc_now()
    _SCAN_STATUS["scan_count"] += 1
    _SCAN_STATUS["last_error"] = None
    try:
        cfg=get_settings()
        _SCAN_STATUS["timeframe"] = cfg["timeframe"]
        from radar_engine import fetch_radar_candles,evaluate_radar,estimate_probability_details
        df=fetch_radar_candles(cfg.get("symbol","BTCUSDT"),cfg["timeframe"])
        higher_df=(fetch_radar_candles(cfg.get("symbol","BTCUSDT"),cfg["higher_timeframe"])
                   if cfg.get("higher_timeframe","none") != "none" else None)
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
        active_markets=open_signal_markets()
        for active_symbol,active_tf in active_markets:
            if active_symbol == cfg.get("symbol","BTCUSDT") and active_tf == cfg["timeframe"]:
                active_df=df
            else:
                active_df=fetch_radar_candles(active_symbol,active_tf)
            track_open_signals(active_df,active_tf,active_symbol)
        candle_id,signal=evaluate_radar(df,cfg,higher_df)
        if not signal:
            log.info("Dashboard scan OK: symbol=%s tf=%s candles=%s candle=%s price=%.2f signal=none",
                     cfg.get("symbol","BTCUSDT"),cfg["timeframe"],len(df),candle_time,price)
            return
        probability_stats=estimate_probability_details(df,cfg,signal["direction"],higher_df=higher_df)
        if not qualifies_by_historical_probability(probability_stats):
            log.info("Dashboard candidate filtered: tf=%s direction=%s probability=%s samples=%s minimum_strictly_above=35%%",
                     cfg["timeframe"],signal["direction"],probability_stats["probability"],probability_stats["samples"])
            return
        signal["probability"] = probability_stats["probability"]
        signal["probability_samples"] = probability_stats["samples"]
        signal["probability_wins"] = probability_stats["wins"]
        signal["probability_ci_low"] = probability_stats["ci_low"]
        signal["probability_ci_high"] = probability_stats["ci_high"]
        config_hash = strategy_hash(cfg)
        stats_epoch = _current_epoch(config_hash)
        signal["strategy_hash"] = config_hash
        signal["config_snapshot"] = dict(cfg)
        signal["stats_epoch"] = stats_epoch
        if not os.getenv("DATABASE_URL", "").strip():
            global _MEM_NEXT_ID
            if any(x["candle_id"] == candle_id and x["timeframe"] == cfg["timeframe"]
                   and x.get("strategy_hash") == config_hash for x in _MEM_SIGNALS):
                log.info("Dashboard scan OK: symbol=%s tf=%s candles=%s price=%.2f signal=duplicate",
                         cfg.get("symbol","BTCUSDT"),cfg["timeframe"],len(df),price)
                return
            signal_row=dict(signal,id=str(_MEM_NEXT_ID),status="CANDIDATE",created_at=_utc_now(),result=None,closed_at=None)
            _MEM_NEXT_ID += 1
            _MEM_SIGNALS.append(signal_row)
            _SCAN_STATUS["last_signal_at"] = _utc_now()
            _push(signal_row)
            log.info("Dashboard scan OK: symbol=%s tf=%s candles=%s candle=%s price=%.2f signal=%s probability=%s",
                     cfg.get("symbol","BTCUSDT"),cfg["timeframe"],len(df),candle_time,price,signal["direction"],signal["probability"])
            return
        with _db() as conn:
            row=conn.execute("""INSERT INTO bgm_dashboard_signals(user_id,candle_id,symbol,timeframe,direction,entry,stop,target,score,maximum,
              probability,probability_samples,probability_wins,probability_ci_low,probability_ci_high,
              confirmations,created_at,strategy_hash,config_snapshot,stats_epoch)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s)
              ON CONFLICT(user_id,candle_id,timeframe,strategy_hash) DO NOTHING RETURNING id""",
              (_TENANT.get(),candle_id,cfg.get("symbol","BTCUSDT"),cfg["timeframe"],signal["direction"],signal["entry"],signal["stop"],signal["target"],
               signal["score"],signal["maximum"],signal["probability"],signal["probability_samples"],signal["probability_wins"],
               signal["probability_ci_low"],signal["probability_ci_high"],json.dumps(signal["confirmations"]),
               config_hash,json.dumps(cfg),stats_epoch)).fetchone()
        if row:
            signal["id"]=str(row["id"])
            _SCAN_STATUS["last_signal_at"] = _utc_now()
            _push(signal)
        log.info("Dashboard scan OK: symbol=%s tf=%s candles=%s candle=%s price=%.2f signal=%s probability=%s new=%s",
                 cfg.get("symbol","BTCUSDT"),cfg["timeframe"],len(df),candle_time,price,signal["direction"],signal["probability"],bool(row))
    except Exception as exc:
        _SCAN_STATUS["last_error"] = type(exc).__name__ + ": " + str(exc)[:300]
        log.exception("Dashboard radar scan failed")

def scan_dashboard():
    """Evaluate the shared market feed independently for every active dashboard account."""
    if not os.getenv("DATABASE_URL", "").strip():
        _SCAN_STATUS["last_error"]="DATABASE_URL obligatorio para multiusuario"
        return
    try:
        with _tenant_scope("__system__"):
            with _db() as conn:
                rows=conn.execute("SELECT user_id FROM bgm_dashboard_tenant_ids()").fetchall()
        for row in rows:
            with _tenant_scope(row["user_id"]):
                _scan_dashboard_for_tenant()
    except Exception as exc:
        _SCAN_STATUS["last_error"]=type(exc).__name__+": "+str(exc)[:300]
        log.exception("Multi-user dashboard scan failed")


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
    if path=="/api/dashboard/login" and handler.command=="POST":
        try:
            payload=_read(handler)
            supplied=str(payload.get("pin") or handler.headers.get("X-Dashboard-Token","")).strip()
            user_id=_user_for_pin(supplied)
            if not user_id: _json(handler,401,{"error":"PIN incorrecto o no habilitado."}); return True
            _json(handler,200,{"ok":True,"token":_create_session(user_id)})
        except Exception:
            log.exception("Dashboard login failed")
            _json(handler,503,{"error":"Servicio de acceso no disponible."})
        return True
    if path=="/api/dashboard/logout" and handler.command=="POST":
        supplied=handler.headers.get("X-Dashboard-Token","")
        digest=hashlib.sha256(supplied.encode("utf-8")).hexdigest()
        with _tenant_scope("__auth__"):
            with _db() as conn: conn.execute("DELETE FROM bgm_dashboard_sessions WHERE token_hash=%s",(digest,))
        _json(handler,200,{"ok":True}); return True
    supplied=handler.headers.get("X-Dashboard-Token","")
    user_id=_user_for_session(supplied)
    if not user_id: _json(handler,401,{"error":"Sesión inválida o vencida. Vuelve a entrar con tu PIN."}); return True
    _TENANT.set(user_id)
    try:
        if path=="/api/dashboard/settings" and handler.command=="GET": _json(handler,200,get_settings())
        elif path=="/api/dashboard/settings" and handler.command=="POST": _json(handler,200,set_settings(_read(handler)))
        elif path=="/api/dashboard/signals" and handler.command=="GET": _json(handler,200,{"signals":list_signals()})
        elif path=="/api/dashboard/trades" and handler.command=="GET": _json(handler,200,list_trades())
        elif path=="/api/dashboard/trades/reset" and handler.command=="POST":
            config_hash = strategy_hash(get_settings())
            if not os.getenv("DATABASE_URL", "").strip():
                _MEM_STATS_EPOCH[config_hash] = _current_epoch(config_hash) + 1
                new_epoch = _MEM_STATS_EPOCH[config_hash]
            else:
                with _db() as conn:
                    row = conn.execute("""INSERT INTO bgm_dashboard_strategy_state(strategy_hash,user_id,epoch,updated_at)
                      VALUES(%s,%s,1,now()) ON CONFLICT(strategy_hash,user_id) DO UPDATE
                      SET epoch=bgm_dashboard_strategy_state.epoch+1,updated_at=now()
                      RETURNING epoch""", (config_hash,_TENANT.get())).fetchone()
                    new_epoch = int(row["epoch"])
            _json(handler,200,{"ok":True,"strategy_hash":config_hash,"stats_epoch":new_epoch})
        elif path=="/api/dashboard/backtest" and handler.command=="POST":
            from radar_engine import fetch_radar_candles
            from radar_backtest import run_backtest
            cfg=get_settings()
            df=fetch_radar_candles(cfg.get("symbol","BTCUSDT"),cfg["timeframe"])
            higher_df=(fetch_radar_candles(cfg.get("symbol","BTCUSDT"),cfg["higher_timeframe"])
                       if cfg.get("higher_timeframe","none") != "none" else None)
            params=_read(handler)
            report=run_backtest(df,cfg,horizon=20,test_fraction=0.30,higher_df=higher_df,
                                starting_capital=params.get("starting_capital",100),
                                risk_pct=params.get("risk_pct",1))
            _json(handler,200,report)
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
