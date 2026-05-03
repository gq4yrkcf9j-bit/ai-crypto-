"""ML Predictor — gradient boosting model trained on technical indicator features
to predict short-term price direction and magnitude."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

from autotrader.tools.indicators import IndicatorSnapshot

logger = logging.getLogger(__name__)

_FEATURE_NAMES = [
    "rsi",
    "rsi_norm",
    "bb_position",
    "macd_histogram",
    "macd_value",
    "stoch_k",
    "stoch_d",
    "adx",
    "plus_di",
    "minus_di",
    "di_spread",
    "atr_pct",
    "obv_slope",
    "price_vs_vwap",
    "sma_spread",
    "ema_vs_price",
    "trend_strength",
]

# Labels: 0=down, 1=flat, 2=up
_LABEL_DOWN = 0
_LABEL_FLAT = 1
_LABEL_UP = 2

# Threshold for labelling price movement (must exceed round-trip fees)
_MOVE_THRESHOLD = 0.008  # 0.8% — must be > round-trip fee to be worth trading


@dataclass
class MLPrediction:
    """Output from the ML predictor."""

    direction: str  # "up", "down", "flat"
    confidence: float  # probability of predicted direction
    up_prob: float
    down_prob: float
    flat_prob: float
    features_used: int
    trained: bool  # whether model has been trained
    sample_count: int  # how many samples model was trained on

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "up_prob": round(self.up_prob, 4),
            "down_prob": round(self.down_prob, 4),
            "flat_prob": round(self.flat_prob, 4),
            "features_used": self.features_used,
            "trained": self.trained,
            "sample_count": self.sample_count,
        }


class MLPredictor:
    """Online-learning gradient boosting classifier for price direction prediction.

    Accumulates (features, label) pairs from completed trades and periodically
    retrains. Until enough data is collected (min_samples), returns a neutral
    prediction so the technical strategy dominates.
    """

    def __init__(self, min_samples: int = 30, max_samples: int = 2000) -> None:
        self._min_samples = min_samples
        self._max_samples = max_samples

        self._features: deque[list[float]] = deque(maxlen=max_samples)
        self._labels: deque[int] = deque(maxlen=max_samples)
        self._pending_features: dict[str, list[float]] = {}  # pair → features at entry
        self._pending_prices: dict[str, float] = {}  # pair → entry price

        self._model: GradientBoostingClassifier | None = None
        self._scaler = StandardScaler()
        self._is_trained = False
        self._retrain_interval = 10  # retrain every N new samples
        self._samples_since_train = 0

    # ------------------------------------------------------------------ #
    #  Predict                                                            #
    # ------------------------------------------------------------------ #
    def predict(self, snapshot: IndicatorSnapshot) -> MLPrediction:
        """Predict price direction from current indicators."""
        features = snapshot.to_feature_vector()
        feature_values = [features.get(name, 0.0) for name in _FEATURE_NAMES]

        if not self._is_trained or self._model is None:
            return MLPrediction(
                direction="flat",
                confidence=0.33,
                up_prob=0.33,
                down_prob=0.33,
                flat_prob=0.34,
                features_used=len(feature_values),
                trained=False,
                sample_count=len(self._features),
            )

        x = np.array([feature_values])
        x_scaled = self._scaler.transform(x)
        probs = self._model.predict_proba(x_scaled)[0]

        # Map class indices to probabilities
        classes = list(self._model.classes_)
        prob_map = {cls: prob for cls, prob in zip(classes, probs)}
        down_prob = prob_map.get(_LABEL_DOWN, 0.0)
        flat_prob = prob_map.get(_LABEL_FLAT, 0.0)
        up_prob = prob_map.get(_LABEL_UP, 0.0)

        if up_prob >= down_prob and up_prob >= flat_prob:
            direction = "up"
            confidence = up_prob
        elif down_prob >= up_prob and down_prob >= flat_prob:
            direction = "down"
            confidence = down_prob
        else:
            direction = "flat"
            confidence = flat_prob

        return MLPrediction(
            direction=direction,
            confidence=confidence,
            up_prob=up_prob,
            down_prob=down_prob,
            flat_prob=flat_prob,
            features_used=len(feature_values),
            trained=True,
            sample_count=len(self._features),
        )

    # ------------------------------------------------------------------ #
    #  Record trade outcomes for training                                 #
    # ------------------------------------------------------------------ #
    def record_entry(self, pair: str, snapshot: IndicatorSnapshot, entry_price: float) -> None:
        """Record features at trade entry for later labelling."""
        features = snapshot.to_feature_vector()
        self._pending_features[pair] = [features.get(name, 0.0) for name in _FEATURE_NAMES]
        self._pending_prices[pair] = entry_price

    def record_exit(self, pair: str, exit_price: float) -> None:
        """Record trade exit and label the training sample."""
        if pair not in self._pending_features:
            return

        entry_price = self._pending_prices.pop(pair, 0.0)
        features = self._pending_features.pop(pair)

        if entry_price <= 0:
            return

        pct_change = (exit_price - entry_price) / entry_price

        if pct_change > _MOVE_THRESHOLD:
            label = _LABEL_UP
        elif pct_change < -_MOVE_THRESHOLD:
            label = _LABEL_DOWN
        else:
            label = _LABEL_FLAT

        self._features.append(features)
        self._labels.append(label)
        self._samples_since_train += 1

        if self._samples_since_train >= self._retrain_interval:
            self._train()

    def add_candle_sample(
        self, features: dict[str, float], future_return: float
    ) -> None:
        """Add a training sample from historical candle data (bootstrap training)."""
        feature_values = [features.get(name, 0.0) for name in _FEATURE_NAMES]

        if future_return > _MOVE_THRESHOLD:
            label = _LABEL_UP
        elif future_return < -_MOVE_THRESHOLD:
            label = _LABEL_DOWN
        else:
            label = _LABEL_FLAT

        self._features.append(feature_values)
        self._labels.append(label)
        self._samples_since_train += 1

    def bootstrap_train(self) -> bool:
        """Force a training cycle (call after adding bootstrap samples)."""
        return self._train()

    # ------------------------------------------------------------------ #
    #  Training                                                           #
    # ------------------------------------------------------------------ #
    def _train(self) -> bool:
        """Retrain the model on accumulated data."""
        n = len(self._features)
        if n < self._min_samples:
            logger.debug("ML: only %d samples, need %d to train", n, self._min_samples)
            return False

        x = np.array(list(self._features))
        y = np.array(list(self._labels))

        # Check we have at least 2 classes
        unique_labels = set(y)
        if len(unique_labels) < 2:
            logger.debug("ML: need at least 2 classes to train, have %d", len(unique_labels))
            return False

        self._scaler.fit(x)
        x_scaled = self._scaler.transform(x)

        self._model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            min_samples_leaf=5,
            random_state=42,
        )
        self._model.fit(x_scaled, y)
        self._is_trained = True
        self._samples_since_train = 0

        logger.info(
            "ML model trained on %d samples | classes=%s | features=%d",
            n,
            sorted(unique_labels),
            x.shape[1],
        )
        return True

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    @property
    def sample_count(self) -> int:
        return len(self._features)
