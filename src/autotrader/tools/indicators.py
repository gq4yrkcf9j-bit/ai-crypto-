"""Technical Indicator Tool — computes moving averages, RSI, Bollinger Bands,
MACD, Stochastic, ADX, VWAP, OBV, ATR, and crossover/regime detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import MACD, ADXIndicator, EMAIndicator, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands

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

    # New indicators
    macd_value: float
    macd_signal: float
    macd_histogram: float
    macd_bullish_cross: bool
    macd_bearish_cross: bool
    stoch_k: float
    stoch_d: float
    stoch_oversold: bool
    stoch_overbought: bool
    adx: float
    adx_trending: bool  # ADX > 25 indicates strong trend
    plus_di: float
    minus_di: float
    atr: float
    atr_pct: float  # ATR as % of price (volatility measure)
    obv_slope: float  # OBV trend direction
    vwap: float
    price_vs_vwap: float  # % above/below VWAP

    # Regime detection
    regime: str  # "trending_up", "trending_down", "ranging"
    trend_strength: float  # 0-1 composite

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
            "macd": round(self.macd_value, 4),
            "macd_signal": round(self.macd_signal, 4),
            "macd_histogram": round(self.macd_histogram, 4),
            "macd_bullish_cross": self.macd_bullish_cross,
            "macd_bearish_cross": self.macd_bearish_cross,
            "stoch_k": round(self.stoch_k, 2),
            "stoch_d": round(self.stoch_d, 2),
            "adx": round(self.adx, 2),
            "adx_trending": self.adx_trending,
            "plus_di": round(self.plus_di, 2),
            "minus_di": round(self.minus_di, 2),
            "atr": round(self.atr, 2),
            "atr_pct": round(self.atr_pct, 4),
            "obv_slope": round(self.obv_slope, 4),
            "vwap": round(self.vwap, 2),
            "price_vs_vwap": round(self.price_vs_vwap, 4),
            "regime": self.regime,
            "trend_strength": round(self.trend_strength, 4),
        }

    def to_feature_vector(self) -> dict[str, float]:
        """Extract numeric features for the ML model."""
        return {
            "rsi": self.rsi,
            "rsi_norm": self.rsi / 100.0,
            "bb_position": (
                (self.current_price - self.bb_lower)
                / (self.bb_upper - self.bb_lower)
                if (self.bb_upper - self.bb_lower) > 0
                else 0.5
            ),
            "macd_histogram": self.macd_histogram,
            "macd_value": self.macd_value,
            "stoch_k": self.stoch_k,
            "stoch_d": self.stoch_d,
            "adx": self.adx,
            "plus_di": self.plus_di,
            "minus_di": self.minus_di,
            "di_spread": self.plus_di - self.minus_di,
            "atr_pct": self.atr_pct,
            "obv_slope": self.obv_slope,
            "price_vs_vwap": self.price_vs_vwap,
            "sma_spread": (
                (self.sma_short - self.sma_long) / self.sma_long if self.sma_long > 0 else 0.0
            ),
            "ema_vs_price": (
                (self.current_price - self.ema_short) / self.ema_short
                if self.ema_short > 0
                else 0.0
            ),
            "trend_strength": self.trend_strength,
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
        """Compute all indicators from a list of candle dicts."""
        if len(candles) < self.long_period + 5:
            logger.warning("Not enough candles (%d) for %s", len(candles), pair)
            return None

        df = pd.DataFrame(candles)
        close: pd.Series = df["close"].astype(float)
        high: pd.Series = df["high"].astype(float)
        low: pd.Series = df["low"].astype(float)
        volume: pd.Series = df["volume"].astype(float)

        # Moving averages
        sma_short_series = SMAIndicator(close, window=self.short_period).sma_indicator()
        sma_long_series = SMAIndicator(close, window=self.long_period).sma_indicator()
        ema_short_series = EMAIndicator(close, window=self.short_period).ema_indicator()

        # RSI
        rsi_series = RSIIndicator(close, window=self.rsi_period).rsi()

        # Bollinger Bands
        bb = BollingerBands(close, window=20, window_dev=2)

        # MACD (12, 26, 9)
        macd_ind = MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_series = macd_ind.macd()
        macd_signal_series = macd_ind.macd_signal()
        macd_hist_series = macd_ind.macd_diff()

        # Stochastic RSI
        stoch_rsi = StochRSIIndicator(close, window=14, smooth1=3, smooth2=3)
        stoch_k_series = stoch_rsi.stochrsi_k()
        stoch_d_series = stoch_rsi.stochrsi_d()

        # ADX
        adx_ind = ADXIndicator(high, low, close, window=14)
        adx_series = adx_ind.adx()
        plus_di_series = adx_ind.adx_pos()
        minus_di_series = adx_ind.adx_neg()

        # ATR
        atr_ind = AverageTrueRange(high, low, close, window=14)
        atr_series = atr_ind.average_true_range()

        # OBV (on-balance volume)
        obv = self._compute_obv(close, volume)

        # VWAP (using available data)
        vwap_val = self._compute_vwap(high, low, close, volume)

        # Latest values
        sma_s = self._last_valid(sma_short_series)
        sma_l = self._last_valid(sma_long_series)
        ema_s = self._last_valid(ema_short_series)
        rsi_val = self._last_valid(rsi_series)
        bb_upper = self._last_valid(bb.bollinger_hband())
        bb_mid = self._last_valid(bb.bollinger_mavg())
        bb_lower = self._last_valid(bb.bollinger_lband())
        current_price = float(close.iloc[-1])

        macd_val = self._last_valid(macd_series)
        macd_sig = self._last_valid(macd_signal_series)
        macd_hist = self._last_valid(macd_hist_series)
        prev_macd = self._prev_valid(macd_series)
        prev_macd_sig = self._prev_valid(macd_signal_series)

        stoch_k = self._last_valid(stoch_k_series) * 100
        stoch_d = self._last_valid(stoch_d_series) * 100

        adx_val = self._last_valid(adx_series)
        plus_di = self._last_valid(plus_di_series)
        minus_di = self._last_valid(minus_di_series)

        atr_val = self._last_valid(atr_series)
        atr_pct = atr_val / current_price if current_price > 0 else 0.0

        obv_slope = self._compute_slope(obv, window=10)

        price_vs_vwap = (
            (current_price - vwap_val) / vwap_val if vwap_val > 0 else 0.0
        )

        # Cross detection (SMA)
        prev_sma_s = self._prev_valid(sma_short_series)
        prev_sma_l = self._prev_valid(sma_long_series)
        golden = prev_sma_s <= prev_sma_l and sma_s > sma_l
        death = prev_sma_s >= prev_sma_l and sma_s < sma_l

        # MACD cross detection
        macd_bull_cross = prev_macd <= prev_macd_sig and macd_val > macd_sig
        macd_bear_cross = prev_macd >= prev_macd_sig and macd_val < macd_sig

        # Regime detection
        regime, trend_strength = self._detect_regime(
            adx_val, plus_di, minus_di, sma_s, sma_l, rsi_val, macd_hist
        )

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
            macd_value=macd_val,
            macd_signal=macd_sig,
            macd_histogram=macd_hist,
            macd_bullish_cross=macd_bull_cross,
            macd_bearish_cross=macd_bear_cross,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
            stoch_oversold=stoch_k < 20,
            stoch_overbought=stoch_k > 80,
            adx=adx_val,
            adx_trending=adx_val > 25,
            plus_di=plus_di,
            minus_di=minus_di,
            atr=atr_val,
            atr_pct=atr_pct,
            obv_slope=obv_slope,
            vwap=vwap_val,
            price_vs_vwap=price_vs_vwap,
            regime=regime,
            trend_strength=trend_strength,
        )
        logger.debug("Indicators for %s: %s", pair, snap.to_dict())
        return snap

    # ------------------------------------------------------------------ #
    #  OBV, VWAP, regime helpers                                          #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        direction = np.sign(close.diff())
        obv = (direction * volume).cumsum()
        return obv

    @staticmethod
    def _compute_vwap(
        high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
    ) -> float:
        typical_price = (high + low + close) / 3
        cumulative_tpv = (typical_price * volume).cumsum()
        cumulative_vol = volume.cumsum()
        vwap_series = cumulative_tpv / cumulative_vol.replace(0, np.nan)
        valid = vwap_series.dropna()
        return float(valid.iloc[-1]) if len(valid) > 0 else 0.0

    @staticmethod
    def _compute_slope(series: pd.Series, window: int = 10) -> float:
        valid = series.dropna()
        if len(valid) < window:
            return 0.0
        recent = valid.iloc[-window:]
        x = np.arange(len(recent), dtype=float)
        y = recent.values.astype(float)
        if np.std(y) == 0:
            return 0.0
        slope = np.polyfit(x, y, 1)[0]
        return float(slope / (np.abs(y).mean() + 1e-10))

    @staticmethod
    def _detect_regime(
        adx: float,
        plus_di: float,
        minus_di: float,
        sma_short: float,
        sma_long: float,
        rsi: float,
        macd_hist: float,
    ) -> tuple[str, float]:
        """Classify current market regime and return (regime, strength)."""
        # ADX-based trending detection
        is_trending = adx > 25

        if is_trending:
            if plus_di > minus_di and sma_short > sma_long:
                regime = "trending_up"
            elif minus_di > plus_di and sma_short < sma_long:
                regime = "trending_down"
            else:
                regime = "ranging"
        else:
            regime = "ranging"

        # Trend strength composite (0-1)
        adx_component = min(adx / 50.0, 1.0)
        di_spread = abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        macd_component = min(abs(macd_hist) / 100.0, 1.0)
        momentum = abs(rsi - 50) / 50.0

        strength = (adx_component * 0.35 + di_spread * 0.25 + macd_component * 0.2 + momentum * 0.2)
        return regime, min(strength, 1.0)

    @staticmethod
    def _last_valid(series: pd.Series) -> float:
        valid = series.dropna()
        return float(valid.iloc[-1]) if len(valid) > 0 else 0.0

    @staticmethod
    def _prev_valid(series: pd.Series) -> float:
        valid = series.dropna()
        return float(valid.iloc[-2]) if len(valid) > 1 else 0.0
