"""Audit logging — writes every decision and trade to SQLite for review."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLogger:
    """Persistent audit log backed by SQLite."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    # ------------------------------------------------------------------ #
    #  Schema                                                             #
    # ------------------------------------------------------------------ #
    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                pair        TEXT    NOT NULL,
                side        TEXT    NOT NULL,
                quantity    REAL    NOT NULL,
                price       REAL    NOT NULL,
                order_id    TEXT,
                strategy    TEXT,
                confidence  REAL,
                reasoning   TEXT,
                stop_loss   REAL,
                take_profit REAL,
                fee_usd     REAL    DEFAULT 0.0,
                status      TEXT    DEFAULT 'filled'
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                pair        TEXT    NOT NULL,
                action      TEXT    NOT NULL,
                reasoning   TEXT,
                data        TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_pnl (
                date        TEXT    PRIMARY KEY,
                realized_pnl REAL  DEFAULT 0.0,
                trade_count  INTEGER DEFAULT 0,
                total_fees   REAL  DEFAULT 0.0
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    #  Trade logging                                                      #
    # ------------------------------------------------------------------ #
    def log_trade(
        self,
        *,
        pair: str,
        side: str,
        quantity: float,
        price: float,
        order_id: str = "",
        strategy: str = "",
        confidence: float = 0.0,
        reasoning: str = "",
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        fee_usd: float = 0.0,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """
            INSERT INTO trades
                (timestamp, pair, side, quantity, price, order_id,
                 strategy, confidence, reasoning, stop_loss, take_profit, fee_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                pair,
                side,
                quantity,
                price,
                order_id,
                strategy,
                confidence,
                reasoning,
                stop_loss,
                take_profit,
                fee_usd,
            ),
        )
        self._conn.commit()
        trade_id = cur.lastrowid or 0
        logger.info(
            "TRADE LOGGED | %s %s %.6f %s @ $%.2f | strategy=%s confidence=%.2f fee=$%.2f",
            side,
            pair,
            quantity,
            pair.split("-")[0],
            price,
            strategy,
            confidence,
            fee_usd,
        )
        return trade_id

    # ------------------------------------------------------------------ #
    #  Decision logging                                                   #
    # ------------------------------------------------------------------ #
    def log_decision(
        self,
        *,
        pair: str,
        action: str,
        reasoning: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO decisions (timestamp, pair, action, reasoning, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, pair, action, reasoning, json.dumps(data or {})),
        )
        self._conn.commit()
        logger.debug("DECISION | %s | %s | %s", pair, action, reasoning)

    # ------------------------------------------------------------------ #
    #  Daily P&L tracking                                                 #
    # ------------------------------------------------------------------ #
    def update_daily_pnl(self, realized_pnl: float) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._conn.execute(
            """
            INSERT INTO daily_pnl (date, realized_pnl, trade_count)
            VALUES (?, ?, 1)
            ON CONFLICT(date) DO UPDATE SET
                realized_pnl = realized_pnl + excluded.realized_pnl,
                trade_count  = trade_count + 1
            """,
            (today, realized_pnl),
        )
        self._conn.commit()

    def get_daily_pnl(self) -> float:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT realized_pnl FROM daily_pnl WHERE date = ?", (today,)
        ).fetchone()
        return float(row["realized_pnl"]) if row else 0.0

    # ------------------------------------------------------------------ #
    #  Queries                                                            #
    # ------------------------------------------------------------------ #
    def get_recent_trades(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trade_history_for_pair(self, pair: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE pair = ? ORDER BY id DESC LIMIT ?", (pair, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
