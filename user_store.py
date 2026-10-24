"""Per-user persistence. Uses PostgreSQL when DATABASE_URL exists; memory fallback is for smoke tests only."""
import json, os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL=os.getenv("DATABASE_URL","").strip()
_MEM_USERS={}
_MEM_STRATEGIES={}
_MEM_SENT=set()
_NEXT_ID=1

def _connect():
    if not DATABASE_URL: raise RuntimeError("DATABASE_URL no configurada")
    return psycopg.connect(DATABASE_URL,row_factory=dict_row,connect_timeout=10)

def init_db():
    if not DATABASE_URL:
        return
    with _connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS bgm_users (
          telegram_user_id BIGINT PRIMARY KEY, chat_id BIGINT NOT NULL, username TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS bgm_strategies (
          id BIGSERIAL PRIMARY KEY, telegram_user_id BIGINT NOT NULL REFERENCES bgm_users(telegram_user_id) ON DELETE CASCADE,
          name TEXT NOT NULL, config JSONB NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(telegram_user_id,name))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS bgm_sent_signals (
          strategy_id BIGINT NOT NULL REFERENCES bgm_strategies(id) ON DELETE CASCADE,
          candle_id TEXT NOT NULL, sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(strategy_id,candle_id))""")

def upsert_user(user_id,chat_id,username):
    uid=int(user_id)
    if not DATABASE_URL:
        _MEM_USERS[uid]={"telegram_user_id":uid,"chat_id":int(chat_id),"username":username}
        return
    with _connect() as conn:
        conn.execute("""INSERT INTO bgm_users(telegram_user_id,chat_id,username) VALUES(%s,%s,%s)
          ON CONFLICT(telegram_user_id) DO UPDATE SET chat_id=EXCLUDED.chat_id,username=EXCLUDED.username,updated_at=now()""",
          (uid,int(chat_id),username))

def create_strategy(user_id,name,config):
    global _NEXT_ID
    uid=int(user_id)
    if not DATABASE_URL:
        if any(x["telegram_user_id"]==uid and x["name"]==name for x in _MEM_STRATEGIES.values()):
            raise ValueError("Ya tienes una subestrategia con ese nombre.")
        sid=_NEXT_ID; _NEXT_ID+=1
        _MEM_STRATEGIES[sid]={"id":sid,"telegram_user_id":uid,"name":name,"config":dict(config),"enabled":True}
        return sid
    with _connect() as conn:
        row=conn.execute("INSERT INTO bgm_strategies(telegram_user_id,name,config) VALUES(%s,%s,%s) RETURNING id",
          (uid,name,json.dumps(config))).fetchone()
        return row["id"]

def list_strategies(user_id):
    uid=int(user_id)
    if not DATABASE_URL:
        return [dict(x) for x in _MEM_STRATEGIES.values() if x["telegram_user_id"]==uid]
    with _connect() as conn:
        return conn.execute("SELECT id,name,config,enabled,created_at FROM bgm_strategies WHERE telegram_user_id=%s ORDER BY id",(uid,)).fetchall()

def get_active_strategies():
    if not DATABASE_URL:
        return [dict(s,chat_id=_MEM_USERS[s["telegram_user_id"]]["chat_id"]) for s in _MEM_STRATEGIES.values()
          if s["enabled"] and s["telegram_user_id"] in _MEM_USERS]
    with _connect() as conn:
        return conn.execute("""SELECT s.id,s.telegram_user_id,s.name,s.config,u.chat_id FROM bgm_strategies s
          JOIN bgm_users u USING(telegram_user_id) WHERE s.enabled=TRUE ORDER BY s.id""").fetchall()

def set_strategy_enabled(user_id,strategy_id,enabled):
    uid,sid=int(user_id),int(strategy_id)
    if not DATABASE_URL:
        s=_MEM_STRATEGIES.get(sid)
        if not s or s["telegram_user_id"]!=uid: return False
        s["enabled"]=bool(enabled); return True
    with _connect() as conn:
        cur=conn.execute("UPDATE bgm_strategies SET enabled=%s,updated_at=now() WHERE id=%s AND telegram_user_id=%s",(bool(enabled),sid,uid))
        return cur.rowcount>0

def delete_strategy(user_id,strategy_id):
    uid,sid=int(user_id),int(strategy_id)
    if not DATABASE_URL:
        s=_MEM_STRATEGIES.get(sid)
        if not s or s["telegram_user_id"]!=uid: return False
        del _MEM_STRATEGIES[sid]
        _MEM_SENT.difference_update(x for x in _MEM_SENT if x[0]==sid)
        return True
    with _connect() as conn:
        cur=conn.execute("DELETE FROM bgm_strategies WHERE id=%s AND telegram_user_id=%s",(sid,uid))
        return cur.rowcount>0

def claim_signal(strategy_id,candle_id):
    key=(int(strategy_id),str(candle_id))
    if not DATABASE_URL:
        if key in _MEM_SENT: return False
        _MEM_SENT.add(key); return True
    with _connect() as conn:
        row=conn.execute("INSERT INTO bgm_sent_signals(strategy_id,candle_id) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING strategy_id",key).fetchone()
        return row is not None
