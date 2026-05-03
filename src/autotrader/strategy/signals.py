"""Signal types used by strategy layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeSignal:
    """A trading signal produced by the strategy layer."""

    pair: str
    action: SignalAction
    confidence: float  # 0.0 – 1.0
    strategy: str
    reasoning: str
    indicators: dict[str, object] = field(default_factory=dict)
    sentiment_score: float = 0.5

    @property
    def is_actionable(self) -> bool:
        return self.action in (SignalAction.BUY, SignalAction.SELL) and self.confidence > 0.0
