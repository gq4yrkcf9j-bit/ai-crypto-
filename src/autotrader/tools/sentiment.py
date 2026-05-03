"""Sentiment Tool — gauges market fear/greed from news headlines."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from textblob import TextBlob

logger = logging.getLogger(__name__)

# Free crypto-news RSS/API endpoints (no key required)
_NEWS_SOURCES = [
    "https://min-api.cryptocompare.com/data/v2/news/?lang=EN&sortOrder=latest",
]


class SentimentTool:
    """Scrapes crypto news headlines and computes an aggregate sentiment score.

    Score range: -1.0 (extreme fear) to +1.0 (extreme greed).
    The ``normalized_score`` property maps this to 0.0–1.0 for easy threshold
    comparison.
    """

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=15, follow_redirects=True)
        self._cached_score: float | None = None
        self._cached_headlines: list[str] = []

    def analyze(self, pair: str = "BTC") -> dict[str, Any]:
        """Return sentiment analysis for the given asset.

        Returns dict with keys: ``score``, ``normalized``, ``label``,
        ``headline_count``, ``sample_headlines``.
        """
        headlines = self._fetch_headlines(pair)
        if not headlines:
            logger.warning("No headlines fetched for %s — returning neutral sentiment", pair)
            return self._neutral()

        scores: list[float] = []
        for h in headlines:
            blob = TextBlob(h)
            scores.append(blob.sentiment.polarity)

        avg = sum(scores) / len(scores)
        self._cached_score = avg
        self._cached_headlines = headlines

        normalized = (avg + 1.0) / 2.0  # map -1..1 → 0..1
        label = "positive" if normalized > 0.6 else ("negative" if normalized < 0.4 else "neutral")

        return {
            "score": round(avg, 4),
            "normalized": round(normalized, 4),
            "label": label,
            "headline_count": len(headlines),
            "sample_headlines": headlines[:5],
        }

    # ------------------------------------------------------------------ #
    #  Internal                                                           #
    # ------------------------------------------------------------------ #
    def _fetch_headlines(self, asset: str) -> list[str]:
        all_headlines: list[str] = []
        for url in _NEWS_SOURCES:
            try:
                resp = self._http.get(url)
                resp.raise_for_status()
                data = resp.json()
                articles = data.get("Data", [])
                for art in articles:
                    title: str = art.get("title", "")
                    if asset.upper() in title.upper() or "CRYPTO" in title.upper():
                        all_headlines.append(title)
            except Exception:
                logger.debug("Failed to fetch from %s", url, exc_info=True)
        return all_headlines

    @staticmethod
    def _neutral() -> dict[str, Any]:
        return {
            "score": 0.0,
            "normalized": 0.5,
            "label": "neutral",
            "headline_count": 0,
            "sample_headlines": [],
        }

    def close(self) -> None:
        self._http.close()
