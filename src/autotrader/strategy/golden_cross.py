"""Golden Cross / Death Cross strategy with sentiment validation."""

from __future__ import annotations

import logging

from autotrader.strategy.base import BaseStrategy
from autotrader.strategy.signals import SignalAction, TradeSignal
from autotrader.tools.indicators import IndicatorSnapshot

logger = logging.getLogger(__name__)


class GoldenCrossStrategy(BaseStrategy):
    """
    Buy when short-term MA crosses above long-term MA (Golden Cross)
    and sentiment is positive.  Sell on Death Cross or RSI overbought.

    Combines:
    - MA crossover detection
    - RSI confirmation
    - Bollinger Band context
    - Sentiment validation
    """

    name = "golden_cross"

    def __init__(self, sentiment_threshold: float = 0.6) -> None:
        self.sentiment_threshold = sentiment_threshold

    def evaluate(
        self,
        pair: str,
        snapshot: IndicatorSnapshot,
        sentiment_score: float,
        has_position: bool,
    ) -> TradeSignal:
        # ---- SELL signals (check first if we hold a position) ---- #
        if has_position:
            # Death Cross → strong sell
            if snapshot.death_cross:
                return TradeSignal(
                    pair=pair,
                    action=SignalAction.SELL,
                    confidence=0.85,
                    strategy=self.name,
                    reasoning="Death Cross detected — short MA crossed below long MA",
                    indicators=snapshot.to_dict(),
                    sentiment_score=sentiment_score,
                )

            # RSI overbought → take profit signal
            if snapshot.rsi_overbought:
                return TradeSignal(
                    pair=pair,
                    action=SignalAction.SELL,
                    confidence=0.70,
                    strategy=self.name,
                    reasoning=f"RSI overbought ({snapshot.rsi:.1f}) — taking profit",
                    indicators=snapshot.to_dict(),
                    sentiment_score=sentiment_score,
                )

            # Price above upper Bollinger Band → possible reversal
            if snapshot.current_price > snapshot.bb_upper:
                return TradeSignal(
                    pair=pair,
                    action=SignalAction.SELL,
                    confidence=0.55,
                    strategy=self.name,
                    reasoning="Price above upper Bollinger Band — potential reversal",
                    indicators=snapshot.to_dict(),
                    sentiment_score=sentiment_score,
                )

        # ---- BUY signals ---- #
        if not has_position:
            # Golden Cross — primary signal
            if snapshot.golden_cross:
                confidence = 0.80
                reasoning_parts = ["Golden Cross detected — short MA crossed above long MA"]

                # Boost confidence with sentiment
                if sentiment_score >= self.sentiment_threshold:
                    confidence += 0.10
                    reasoning_parts.append(
                        f"Positive sentiment ({sentiment_score:.2f}) confirms momentum"
                    )
                else:
                    confidence -= 0.15
                    reasoning_parts.append(
                        f"Weak sentiment ({sentiment_score:.2f}) reduces confidence"
                    )

                # RSI confirmation
                if snapshot.rsi_oversold:
                    confidence += 0.05
                    reasoning_parts.append("RSI oversold adds upside potential")

                confidence = min(confidence, 1.0)
                return TradeSignal(
                    pair=pair,
                    action=SignalAction.BUY,
                    confidence=confidence,
                    strategy=self.name,
                    reasoning=" | ".join(reasoning_parts),
                    indicators=snapshot.to_dict(),
                    sentiment_score=sentiment_score,
                )

            # Oversold RSI + price near lower Bollinger Band (no cross needed)
            if snapshot.rsi_oversold and snapshot.current_price <= snapshot.bb_lower * 1.01:
                if sentiment_score >= self.sentiment_threshold:
                    return TradeSignal(
                        pair=pair,
                        action=SignalAction.BUY,
                        confidence=0.60,
                        strategy=self.name,
                        reasoning=(
                            f"RSI oversold ({snapshot.rsi:.1f}) + price near lower BB "
                            f"+ positive sentiment ({sentiment_score:.2f})"
                        ),
                        indicators=snapshot.to_dict(),
                        sentiment_score=sentiment_score,
                    )

        # ---- No signal ---- #
        return TradeSignal(
            pair=pair,
            action=SignalAction.HOLD,
            confidence=0.0,
            strategy=self.name,
            reasoning="No actionable pattern detected",
            indicators=snapshot.to_dict(),
            sentiment_score=sentiment_score,
        )
