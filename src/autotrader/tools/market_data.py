"""Market Data Tool — fetches real-time price candles and ticker data from Coinbase."""

from __future__ import annotations

import logging
import time
from typing import Any

from coinbase.rest import RESTClient

from autotrader.config import Config

logger = logging.getLogger(__name__)

# Simulated prices for paper trading when no API credentials are available
_PAPER_PRICES: dict[str, float] = {
    "BTC-USD": 68_400.0,
    "ETH-USD": 3_820.0,
    "SOL-USD": 172.0,
    "DOGE-USD": 0.165,
}


class MarketDataTool:
    """Provides market data from Coinbase or simulated data for paper trading."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: RESTClient | None = None
        if config.has_credentials:
            self._client = RESTClient(
                api_key=config.coinbase_api_key,
                api_secret=config.coinbase_api_secret,
            )

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #
    def get_current_price(self, pair: str) -> float:
        if self._client is not None:
            price = self._fetch_live_price(pair)
            if price > 0:
                return price
            # Fallback to simulation when API fails (e.g. paper mode)
            if self._config.trading_mode.value == "paper":
                return self._simulate_price(pair)
            return 0.0
        return self._simulate_price(pair)

    def get_candles(
        self,
        pair: str,
        granularity: str = "ONE_HOUR",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self._client is not None:
            candles = self._fetch_live_candles(pair, granularity, limit)
            if candles:
                return candles
            # Fallback to simulation when API fails (e.g. paper mode)
            if self._config.trading_mode.value == "paper":
                return self._generate_paper_candles(pair, limit)
            return []
        return self._generate_paper_candles(pair, limit)

    def get_ticker(self, pair: str) -> dict[str, Any]:
        if self._client is not None:
            return self._fetch_live_ticker(pair)
        price = self._simulate_price(pair)
        return {
            "pair": pair,
            "price": price,
            "volume_24h": 0.0,
            "bid": price * 0.999,
            "ask": price * 1.001,
        }

    # ------------------------------------------------------------------ #
    #  Live data (Coinbase Advanced Trade API)                            #
    # ------------------------------------------------------------------ #
    def _fetch_live_price(self, pair: str) -> float:
        assert self._client is not None
        try:
            product = self._client.get_product(pair)
            return float(product["price"])
        except Exception:
            logger.exception("Failed to fetch live price for %s", pair)
            return 0.0

    def _fetch_live_candles(self, pair: str, granularity: str, limit: int) -> list[dict[str, Any]]:
        assert self._client is not None
        try:
            now = int(time.time())
            granularity_seconds = {
                "ONE_MINUTE": 60,
                "FIVE_MINUTE": 300,
                "FIFTEEN_MINUTE": 900,
                "ONE_HOUR": 3600,
                "SIX_HOUR": 21600,
                "ONE_DAY": 86400,
            }
            seconds = granularity_seconds.get(granularity, 3600)
            start = now - (limit * seconds)
            resp = self._client.get_candles(
                product_id=pair,
                start=str(start),
                end=str(now),
                granularity=granularity,
            )
            candles_raw = resp.get("candles", []) if isinstance(resp, dict) else resp
            candles: list[dict[str, Any]] = []
            for c in candles_raw:
                if isinstance(c, dict):
                    candles.append(
                        {
                            "timestamp": c.get("start", ""),
                            "open": float(c.get("open", 0)),
                            "high": float(c.get("high", 0)),
                            "low": float(c.get("low", 0)),
                            "close": float(c.get("close", 0)),
                            "volume": float(c.get("volume", 0)),
                        }
                    )
            return candles
        except Exception:
            logger.exception("Failed to fetch candles for %s", pair)
            return []

    def _fetch_live_ticker(self, pair: str) -> dict[str, Any]:
        assert self._client is not None
        try:
            product = self._client.get_product(pair)
            return {
                "pair": pair,
                "price": float(product.get("price", 0)),
                "volume_24h": float(product.get("volume_24h", 0)),
                "bid": float(product.get("bid", 0)),
                "ask": float(product.get("ask", 0)),
            }
        except Exception:
            logger.exception("Failed to fetch ticker for %s", pair)
            return {"pair": pair, "price": 0.0, "volume_24h": 0.0, "bid": 0.0, "ask": 0.0}

    # ------------------------------------------------------------------ #
    #  Paper trading simulation                                           #
    # ------------------------------------------------------------------ #
    def _simulate_price(self, pair: str) -> float:
        import random

        base = _PAPER_PRICES.get(pair, 100.0)
        jitter = base * random.uniform(-0.005, 0.005)
        return round(base + jitter, 2)

    def _generate_paper_candles(self, pair: str, limit: int) -> list[dict[str, Any]]:
        import random

        base = _PAPER_PRICES.get(pair, 100.0)
        candles: list[dict[str, Any]] = []
        price = base * 0.95
        now = int(time.time())
        for i in range(limit):
            change = price * random.uniform(-0.02, 0.02)
            o = price
            c = price + change
            h = max(o, c) * (1 + random.uniform(0, 0.005))
            low = min(o, c) * (1 - random.uniform(0, 0.005))
            vol = random.uniform(10, 500)
            candles.append(
                {
                    "timestamp": str(now - (limit - i) * 3600),
                    "open": round(o, 2),
                    "high": round(h, 2),
                    "low": round(low, 2),
                    "close": round(c, 2),
                    "volume": round(vol, 4),
                }
            )
            price = c
        return candles
