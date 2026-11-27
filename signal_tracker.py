"""Automatic SL/TP lifecycle tracking for BTC radar signals.

A signal remains active indefinitely until a closed market candle reaches SL or TP.
When both are inside one candle range, the outcome is marked LOSS conservatively.
"""
from datetime import datetime, timezone
import os


def resolve_directional_outcome(direction, high, low, stop, target):
    if direction == "LONG":
        stop_hit, target_hit = float(low) <= float(stop), float(high) >= float(target)
    else:
        stop_hit, target_hit = float(high) >= float(stop), float(low) <= float(target)
    if stop_hit and target_hit:
        return "LOSS", "BOTH_LEVELS_TOUCHED_SAME_CANDLE"
    if stop_hit:
        return "LOSS", "STOP_LOSS"
    if target_hit:
        return "WIN", "TAKE_PROFIT"
    return None, None


def track_memory_signals(signals, candle):
    """Update in-memory records in place; never remove a record from history."""
    closed = []
    for item in signals:
        if item.get("status") not in ("CONFIRMED", "OPEN") or item.get("result"):
            continue
        result, reason = resolve_directional_outcome(
            item["direction"], candle["high"], candle["low"], item["stop"], item["target"]
        )
        if result:
            item["result"] = result
            item["result_reason"] = reason
            item["closed_at"] = datetime.now(timezone.utc).isoformat()
            item["status"] = "CLOSED"
            closed.append(item)
    return closed


def track_database_signals(candle, database_url):
    """Atomically close every active signal touched by this completed candle."""
    import psycopg
    from psycopg.rows import dict_row
    closed = []
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10) as conn:
        rows = conn.execute(
            """SELECT id,direction,stop,target FROM bgm_dashboard_signals
               WHERE status IN ('CONFIRMED','OPEN') AND result IS NULL
               ORDER BY id"""
        ).fetchall()
        for row in rows:
            result, reason = resolve_directional_outcome(
                row["direction"], candle["high"], candle["low"], row["stop"], row["target"]
            )
            if not result:
                continue
            updated = conn.execute(
                """UPDATE bgm_dashboard_signals
                   SET status='CLOSED',result=%s,closed_at=now(),
                       result_reason=%s
                   WHERE id=%s AND result IS NULL
                   RETURNING id,result,result_reason,closed_at""",
                (result, reason, row["id"]),
            ).fetchone()
            if updated:
                closed.append(dict(updated))
    return closed
