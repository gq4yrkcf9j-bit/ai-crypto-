"""Ensemble Signal Combiner — merges ML prediction, technical analysis, and
sentiment into a single weighted trade signal with fee-aware filtering."""

from __future__ import annotations

import logging

from autotrader.config import Config
from autotrader.ml.predictor import MLPrediction
from autotrader.strategy.signals import SignalAction, TradeSignal
from autotrader.tools.indicators import IndicatorSnapshot

logger = logging.getLogger(__name__)


class EnsembleStrategy:
    """Combines ML prediction, technical indicator signals, and sentiment
    into one confidence-weighted trade signal.

    The ensemble only recommends trades whose expected return exceeds the
    Coinbase round-trip fee plus a minimum profit margin.
    """

    name = "ensemble"

    def __init__(self, config: Config) -> None:
        self._config = config
        self._ml_weight = config.ml_model_weight
        self._tech_weight = config.technical_weight
        self._sent_weight = config.sentiment_weight
        self._min_confidence = config.min_signal_confidence
        self._round_trip_fee = config.round_trip_fee_pct
        self._min_profit_after_fees = config.min_profit_after_fees_pct

    def evaluate(
        self,
        pair: str,
        snapshot: IndicatorSnapshot,
        ml_prediction: MLPrediction,
        sentiment_score: float,
        has_position: bool,
    ) -> TradeSignal:
        """Generate a trade signal from all inputs."""
        # Compute component scores (each -1 to +1, where +1 = strong buy)
        tech_score = self._technical_score(snapshot, has_position)
        ml_score = self._ml_score(ml_prediction)
        sent_score = self._sentiment_score(sentiment_score)

        # Weighted ensemble
        if ml_prediction.trained:
            raw = (
                tech_score * self._tech_weight
                + ml_score * self._ml_weight
                + sent_score * self._sent_weight
            )
        else:
            # ML not trained yet — redistribute weight to tech
            effective_tech = self._tech_weight + self._ml_weight * 0.7
            effective_sent = self._sent_weight + self._ml_weight * 0.3
            raw = tech_score * effective_tech + sent_score * effective_sent

        # Map raw score (-1..+1) to action + confidence
        action, confidence = self._raw_to_action(raw, has_position)

        # Fee-aware filtering: only BUY if expected return exceeds fees
        reasoning_parts: list[str] = []

        if action == SignalAction.BUY:
            min_required = self._round_trip_fee + self._min_profit_after_fees
            expected_return = self._estimate_return(snapshot, confidence)

            if expected_return < min_required:
                reasoning_parts.append(
                    f"Expected return {expected_return:.2%} < fees+min "
                    f"{min_required:.2%} — skipping"
                )
                action = SignalAction.HOLD
                confidence = 0.0
            else:
                reasoning_parts.append(
                    f"Expected return {expected_return:.2%} > fees "
                    f"{self._round_trip_fee:.2%} — profitable entry"
                )

        # Build reasoning
        reasoning_parts.insert(0, f"Regime: {snapshot.regime}")
        reasoning_parts.append(
            f"Tech={tech_score:+.2f} ML={ml_score:+.2f} "
            f"Sent={sent_score:+.2f} → raw={raw:+.3f}"
        )
        if ml_prediction.trained:
            reasoning_parts.append(
                f"ML: {ml_prediction.direction} ({ml_prediction.confidence:.0%})"
            )
        else:
            reasoning_parts.append(f"ML: warming up ({ml_prediction.sample_count} samples)")

        # Regime-based confidence adjustment
        if snapshot.regime == "ranging" and action in (SignalAction.BUY, SignalAction.SELL):
            confidence *= 0.8
            reasoning_parts.append("Ranging market — confidence reduced")
        elif snapshot.adx_trending and snapshot.trend_strength > 0.6:
            confidence = min(confidence * 1.1, 1.0)
            reasoning_parts.append("Strong trend — confidence boosted")

        # Final confidence gate
        if action != SignalAction.HOLD and confidence < self._min_confidence:
            reasoning_parts.append(
                f"Confidence {confidence:.2f} < min {self._min_confidence} — holding"
            )
            action = SignalAction.HOLD
            confidence = 0.0

        return TradeSignal(
            pair=pair,
            action=action,
            confidence=confidence,
            strategy=self.name,
            reasoning=" | ".join(reasoning_parts),
            indicators=snapshot.to_dict(),
            sentiment_score=sentiment_score,
        )

    # ------------------------------------------------------------------ #
    #  Component scoring                                                  #
    # ------------------------------------------------------------------ #
    def _technical_score(self, snap: IndicatorSnapshot, has_position: bool) -> float:
        """Score from -1 (strong sell) to +1 (strong buy) based on indicators."""
        score = 0.0

        # Trend following signals
        if snap.golden_cross:
            score += 0.30
        elif snap.death_cross:
            score -= 0.30

        # MACD
        if snap.macd_bullish_cross:
            score += 0.20
        elif snap.macd_bearish_cross:
            score -= 0.20
        elif snap.macd_histogram > 0:
            score += 0.05
        elif snap.macd_histogram < 0:
            score -= 0.05

        # SMA trend
        if snap.sma_short > snap.sma_long:
            score += 0.10
        else:
            score -= 0.10

        # RSI
        if snap.rsi_oversold:
            score += 0.15  # mean reversion buy signal
        elif snap.rsi_overbought:
            score -= 0.15  # overbought sell signal
        elif snap.rsi < 45:
            score += 0.05
        elif snap.rsi > 55:
            score -= 0.05

        # Stochastic
        if snap.stoch_oversold and snap.stoch_k > snap.stoch_d:
            score += 0.10  # oversold + turning up
        elif snap.stoch_overbought and snap.stoch_k < snap.stoch_d:
            score -= 0.10  # overbought + turning down

        # Bollinger Band position
        bb_pos = (
            (snap.current_price - snap.bb_lower) / (snap.bb_upper - snap.bb_lower)
            if snap.bb_upper > snap.bb_lower
            else 0.5
        )
        if bb_pos < 0.15:
            score += 0.10  # near lower band
        elif bb_pos > 0.85:
            score -= 0.10  # near upper band

        # OBV trend (volume confirms price)
        if snap.obv_slope > 0.01:
            score += 0.05
        elif snap.obv_slope < -0.01:
            score -= 0.05

        # VWAP
        if snap.price_vs_vwap < -0.005:
            score += 0.05  # below VWAP — potential value
        elif snap.price_vs_vwap > 0.005:
            score -= 0.05  # above VWAP — potentially overvalued

        return max(-1.0, min(1.0, score))

    @staticmethod
    def _ml_score(prediction: MLPrediction) -> float:
        """Convert ML prediction to -1..+1 score."""
        if not prediction.trained:
            return 0.0

        if prediction.direction == "up":
            return prediction.confidence * 2 - 1  # map 0.5..1.0 → 0..1
        elif prediction.direction == "down":
            return -(prediction.confidence * 2 - 1)
        return 0.0

    @staticmethod
    def _sentiment_score(normalized: float) -> float:
        """Convert 0..1 sentiment to -1..+1 score."""
        return (normalized - 0.5) * 2

    # ------------------------------------------------------------------ #
    #  Action mapping                                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _raw_to_action(
        raw_score: float, has_position: bool
    ) -> tuple[SignalAction, float]:
        """Map composite score to action + confidence."""
        if raw_score > 0.15 and not has_position:
            confidence = min(raw_score, 1.0)
            return SignalAction.BUY, confidence
        elif raw_score < -0.15 and has_position:
            confidence = min(abs(raw_score), 1.0)
            return SignalAction.SELL, confidence
        return SignalAction.HOLD, 0.0

    def _estimate_return(self, snap: IndicatorSnapshot, confidence: float) -> float:
        """Estimate expected return from current indicators and confidence."""
        # Base expected return from ATR (avg price swing)
        atr_return = snap.atr_pct

        # Scale by trend strength and confidence
        return atr_return * snap.trend_strength * confidence
