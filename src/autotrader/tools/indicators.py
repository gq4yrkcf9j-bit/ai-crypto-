"""Technical Indicator Tool — computes moving averages, RSI, Bollinger Bands, etc."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, SMAIndicator
from ta.volatility import BollingerBands

logger = logging.getLogger(__name__)


@dataclass
class IndicatorSnapshot:
    """All computed indicators for a given pair at a point in time."""

    pair: str
    current_price: float
    sma_short: float
    sma_long: float
    ema_short: float
    rsi: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    golden_cross: bool
    death_cross: bool
    rsi_oversold: bool
    rsi_overbought: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair": self.pair,
            "current_price": self.current_price,
            "sma_short": round(self.sma_short, 2),
            "sma_long": round(self.sma_long, 2),
            "ema_short": round(self.ema_short, 2),
            "rsi": round(self.rsi, 2),
            "bb_upper": round(self.bb_upper, 2),
            "bb_middle": round(self.bb_middle, 2),
            "bb_lower": round(self.bb_lower, 2),
            "golden_cross": self.golden_cross,
            "death_cross": self.death_cross,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
        }


class TechnicalIndicatorTool:
    """Computes technical indicators from OHLCV candle data."""

    def __init__(
        self,
        short_period: int = 20,
        long_period: int = 50,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
    ) -> None:
        self.short_period = short_period
        self.long_period = long_period
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def compute(self, pair: str, candles: list[dict[str, Any]]) -> IndicatorSnapshot | None:
        """Compute all indicators from a list of candle dicts.

        Each candle must have keys: ``open``, ``high``, ``low``, ``close``, ``volume``.
        """
        if len(candles) < self.long_period + 5:
            logger.warning("Not enough candles (%d) for %s", len(candles), pair)
            return None

        df = pd.DataFrame(candles)
        close: pd.Series = df["close"].astype(float)

        # Moving averages
        sma_short_series = SMAIndicator(close, window=self.short_period).sma_indicator()
        sma_long_series = SMAIndicator(close, window=self.long_period).sma_indicator()
        ema_short_series = EMAIndicator(close, window=self.short_period).ema_indicator()

        # RSI
        rsi_series = RSIIndicator(close, window=self.rsi_period).rsi()

        # Bollinger Bands
        bb = BollingerBands(close, window=20, window_dev=2)

        # Latest values
        sma_s = self._last_valid(sma_short_series)
        sma_l = self._last_valid(sma_long_series)
        ema_s = self._last_valid(ema_short_series)
        rsi_val = self._last_valid(rsi_series)
        bb_upper = self._last_valid(bb.bollinger_hband())
        bb_mid = self._last_valid(bb.bollinger_mavg())
        bb_lower = self._last_valid(bb.bollinger_lband())
        current_price = float(close.iloc[-1])

        # Previous values for cross detection
        prev_sma_s = self._prev_valid(sma_short_series)
        prev_sma_l = self._prev_valid(sma_long_series)

        golden = prev_sma_s <= prev_sma_l and sma_s > sma_l
        death = prev_sma_s >= prev_sma_l and sma_s < sma_l

        snap = IndicatorSnapshot(
            pair=pair,
            current_price=current_price,
            sma_short=sma_s,
            sma_long=sma_l,
            ema_short=ema_s,
            rsi=rsi_val,
            bb_upper=bb_upper,
            bb_middle=bb_mid,
            bb_lower=bb_lower,
            golden_cross=golden,
            death_cross=death,
            rsi_oversold=rsi_val < self.rsi_oversold,
            rsi_overbought=rsi_val > self.rsi_overbought,
        )
        logger.debug("Indicators for %s: %s", pair, snap.to_dict())
        return snap

    @staticmethod
    def _last_valid(series: pd.Series) -> float:
        valid = series.dropna()
        return float(valid.iloc[-1]) if len(valid) > 0 else 0.0

    @staticmethod
    def _prev_valid(series: pd.Series) -> float:
        valid = series.dropna()
        return float(valid.iloc[-2]) if len(valid) > 1 else 0.0
