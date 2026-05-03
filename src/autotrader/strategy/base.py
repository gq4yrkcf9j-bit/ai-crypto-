"""Base strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from autotrader.strategy.signals import TradeSignal
from autotrader.tools.indicators import IndicatorSnapshot


class BaseStrategy(ABC):
    """All strategies implement this interface."""

    name: str = "base"

    @abstractmethod
    def evaluate(
        self,
        pair: str,
        snapshot: IndicatorSnapshot,
        sentiment_score: float,
        has_position: bool,
    ) -> TradeSignal:
        """Evaluate market data and return a trade signal."""
        ...
