"""PostgreSQL-backed, privacy-conscious analytics for BGM Quant Lab."""
from __future__ import annotations
import hashlib
import os
from datetime import date, datetime, timedelta, timezone

def _connect():
    url = os.getenv("QUANT_ANALYTICS_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("QUANT_ANALYTICS_DATABASE_URL is not configured")
    import psycopg
    return psycopg.connect(url, connect_timeout=5)

def _init(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS quant_lab_analytics_events (
          id BIGSERIAL PRIMARY KEY,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          event_type TEXT NOT NULL,
          visitor_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          page_path TEXT NOT NULL DEFAULT '/',
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS qla_events_time_idx ON quant_lab_analytics_events (occurred_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS qla_events_type_time_idx ON quant_lab_analytics_events (event_type, occurred_at)")
    conn.commit()

def record_event(payload):
    event_type = str(payload.get("event_type", ""))[:40]
    visitor_id = str(payload.get("visitor_id", ""))[:80]
    session_id = str(payload.get("session_id", ""))[:80]
    page_path = str(payload.get("page_path", "/"))[:180]
    allowed = {"page_view", "strategy_saved", "strategy_interpreted", "backtest_completed", "client_error"}
    if event_type not in allowed or not visitor_id or not session_id:
        raise ValueError("Invalid analytics event")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    safe = {}
    for key in ("timeframe", "market", "trades", "net_return_pct", "status"):
        value = metadata.get(key)
        if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 80:
            safe[key] = value
    import json
    with _connect() as conn:
        _init(conn)
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO quant_lab_analytics_events
              (event_type, visitor_id, session_id, page_path, metadata)
              VALUES (%s,%s,%s,%s,%s::jsonb)""",
              (event_type, visitor_id, session_id, page_path, json.dumps(safe)))
        conn.commit()

def daily_report(days=1):
    days = max(1, min(int(days), 31))
    with _connect() as conn:
        _init(conn)
        with conn.cursor() as cur:
            cur.execute("""
            SELECT
              COUNT(*) FILTER (WHERE event_type='page_view') AS page_views,
              COUNT(DISTINCT visitor_id) AS unique_visitors,
              COUNT(DISTINCT session_id) AS sessions,
              COUNT(*) FILTER (WHERE event_type='strategy_saved') AS strategies_saved,
              COUNT(*) FILTER (WHERE event_type='strategy_interpreted') AS interpretations,
              COUNT(*) FILTER (WHERE event_type='backtest_completed') AS backtests,
              COUNT(*) FILTER (WHERE event_type='client_error') AS client_errors
            FROM quant_lab_analytics_events
            WHERE occurred_at >= NOW() - (%s * INTERVAL '1 day')
            """, (days,))
            row = cur.fetchone()
            cur.execute("""SELECT page_path, COUNT(*) AS views
              FROM quant_lab_analytics_events
              WHERE event_type='page_view' AND occurred_at >= NOW() - (%s * INTERVAL '1 day')
              GROUP BY page_path ORDER BY views DESC LIMIT 10""", (days,))
            pages = [{"path": r[0], "views": r[1]} for r in cur.fetchall()]
            cur.execute("""SELECT event_type, COUNT(*) FROM quant_lab_analytics_events
              WHERE occurred_at >= NOW() - (%s * INTERVAL '1 day')
              GROUP BY event_type ORDER BY COUNT(*) DESC""", (days,))
            events = [{"event": r[0], "count": r[1]} for r in cur.fetchall()]
    keys = ["page_views", "unique_visitors", "sessions", "strategies_saved", "interpretations", "backtests", "client_errors"]
    return {"period_days": days, **dict(zip(keys, row)), "top_pages": pages, "event_breakdown": events,
            "generated_at": datetime.now(timezone.utc).isoformat(), "storage": "postgresql"}

def is_configured():
    return bool(os.getenv("QUANT_ANALYTICS_DATABASE_URL", "").strip())
