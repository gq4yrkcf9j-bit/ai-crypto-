"""Memory store — short-term and long-term memory for the trading agent."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open position."""

    pair: str
    side: str  # "buy"
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    order_id: str = ""

    @property
    def notional_value(self) -> float:
        return self.quantity * self.entry_price


@dataclass
class TradeResult:
    """Outcome of a closed trade — stored in long-term memory."""

    pair: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    strategy: str
    reasoning: str
    closed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MemoryStore:
    """Manages short-term (working) memory and long-term (historical) memory."""

    def __init__(self, max_short_term: int = 200, max_long_term: int = 1000) -> None:
        # Short-term: recent candles and open positions
        self.recent_candles: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max_short_term)
        )
        self.open_positions: dict[str, Position] = {}
        self.pending_orders: dict[str, dict[str, Any]] = {}

        # Long-term: closed trade results
        self.trade_history: deque[TradeResult] = deque(maxlen=max_long_term)
        self.win_count: int = 0
        self.loss_count: int = 0

    # ------------------------------------------------------------------ #
    #  Short-term memory                                                  #
    # ------------------------------------------------------------------ #
    def store_candles(self, pair: str, candles: list[dict[str, Any]]) -> None:
        for c in candles:
            self.recent_candles[pair].append(c)

    def get_candles(self, pair: str) -> list[dict[str, Any]]:
        return list(self.recent_candles[pair])

    def open_position(self, position: Position) -> None:
        self.open_positions[position.pair] = position
        logger.info(
            "POSITION OPENED | %s %.6f @ $%.2f",
            position.pair,
            position.quantity,
            position.entry_price,
        )

    def close_position(
        self,
        pair: str,
        exit_price: float,
        strategy: str = "",
        reasoning: str = "",
    ) -> TradeResult | None:
        pos = self.open_positions.pop(pair, None)
        if pos is None:
            return None

        pnl = (exit_price - pos.entry_price) * pos.quantity
        result = TradeResult(
            pair=pair,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl=pnl,
            strategy=strategy,
            reasoning=reasoning,
        )
        self.trade_history.append(result)
        if pnl >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1

        logger.info(
            "POSITION CLOSED | %s | PnL: $%.2f | entry=$%.2f exit=$%.2f",
            pair,
            pnl,
            pos.entry_price,
            exit_price,
        )
        return result

    def has_open_position(self, pair: str) -> bool:
        return pair in self.open_positions

    def get_position(self, pair: str) -> Position | None:
        return self.open_positions.get(pair)

    # ------------------------------------------------------------------ #
    #  Long-term memory                                                   #
    # ------------------------------------------------------------------ #
    @property
    def win_rate(self) -> float:
        total = self.win_count + self.loss_count
        return self.win_count / total if total > 0 else 0.0

    def get_pair_performance(self, pair: str) -> dict[str, Any]:
        pair_trades = [t for t in self.trade_history if t.pair == pair]
        if not pair_trades:
            return {"pair": pair, "trades": 0, "total_pnl": 0.0, "avg_pnl": 0.0}
        total_pnl = sum(t.pnl for t in pair_trades)
        return {
            "pair": pair,
            "trades": len(pair_trades),
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(pair_trades),
            "wins": sum(1 for t in pair_trades if t.pnl >= 0),
            "losses": sum(1 for t in pair_trades if t.pnl < 0),
        }

    def should_avoid_pair(self, pair: str, loss_threshold: int = 3) -> bool:
        """Check if the agent has recently lost too many consecutive trades on a pair."""
        pair_trades = [t for t in self.trade_history if t.pair == pair]
        if len(pair_trades) < loss_threshold:
            return False
        recent = pair_trades[-loss_threshold:]
        return all(t.pnl < 0 for t in recent)
