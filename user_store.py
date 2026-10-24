"""PostgreSQL persistence for per-Telegram-user BGM strategies."""
import json
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada. Conecta una base PostgreSQL persistente.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bgm_users (
                telegram_user_id BIGINT PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                username TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bgm_strategies (
                id BIGSERIAL PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL REFERENCES bgm_users(telegram_user_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                config JSONB NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(telegram_user_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bgm_sent_signals (
                strategy_id BIGINT NOT NULL REFERENCES bgm_strategies(id) ON DELETE CASCADE,
                candle_id TEXT NOT NULL,
                sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(strategy_id, candle_id)
            )
        """)


def upsert_user(user_id, chat_id, username):
    with _connect() as conn:
        conn.execute("""
            INSERT INTO bgm_users(telegram_user_id, chat_id, username)
            VALUES (%s, %s, %s)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                chat_id=EXCLUDED.chat_id, username=EXCLUDED.username, updated_at=now()
        """, (int(user_id), int(chat_id), username))


def create_strategy(user_id, name, config):
    with _connect() as conn:
        row = conn.execute("""
            INSERT INTO bgm_strategies(telegram_user_id, name, config)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (int(user_id), name, json.dumps(config))).fetchone()
        return row["id"]


def list_strategies(user_id):
    with _connect() as conn:
        return conn.execute("""
            SELECT id, name, config, enabled, created_at
            FROM bgm_strategies WHERE telegram_user_id=%s ORDER BY id
        """, (int(user_id),)).fetchall()


def get_active_strategies():
    with _connect() as conn:
        return conn.execute("""
            SELECT s.id, s.telegram_user_id, s.name, s.config, u.chat_id
            FROM bgm_strategies s JOIN bgm_users u USING (telegram_user_id)
            WHERE s.enabled=TRUE ORDER BY s.id
        """).fetchall()


def set_strategy_enabled(user_id, strategy_id, enabled):
    with _connect() as conn:
        cur = conn.execute("""
            UPDATE bgm_strategies SET enabled=%s, updated_at=now()
            WHERE id=%s AND telegram_user_id=%s
        """, (bool(enabled), int(strategy_id), int(user_id)))
        return cur.rowcount > 0


def delete_strategy(user_id, strategy_id):
    with _connect() as conn:
        cur = conn.execute("""
            DELETE FROM bgm_strategies WHERE id=%s AND telegram_user_id=%s
        """, (int(strategy_id), int(user_id)))
        return cur.rowcount > 0


def claim_signal(strategy_id, candle_id):
    """Atomic dedupe: True only for the first process that claims this candle."""
    with _connect() as conn:
        row = conn.execute("""
            INSERT INTO bgm_sent_signals(strategy_id, candle_id)
            VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING strategy_id
        """, (int(strategy_id), str(candle_id))).fetchone()
        return row is not None
