"""Configuration for the AI Crypto Trader."""

from __future__ import annotations

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Coinbase Credentials ---
    coinbase_api_key: str = Field(default="", description="Coinbase Advanced Trade API key")
    coinbase_api_secret: str = Field(default="", description="Coinbase Advanced Trade API secret")

    # --- Trading Parameters ---
    trading_mode: TradingMode = Field(default=TradingMode.PAPER, description="paper or live")
    trading_pairs: list[str] = Field(
        default=["BTC-USD", "ETH-USD"], description="Crypto pairs to trade"
    )
    scan_interval_seconds: int = Field(default=60, description="Seconds between scan cycles")

    # --- Risk Management ---
    max_position_pct: float = Field(
        default=0.02, description="Max % of wallet per trade (2% default)"
    )
    daily_loss_limit_pct: float = Field(
        default=0.05, description="Max daily loss % before kill switch (5% default)"
    )
    default_stop_loss_pct: float = Field(
        default=0.03, description="Default stop-loss % below entry (3%)"
    )
    default_take_profit_pct: float = Field(
        default=0.06, description="Default take-profit % above entry (6%)"
    )

    # --- Strategy Parameters ---
    short_ma_period: int = Field(default=20, description="Short moving average period")
    long_ma_period: int = Field(default=50, description="Long moving average period")
    rsi_period: int = Field(default=14, description="RSI period")
    rsi_oversold: float = Field(default=30.0, description="RSI oversold threshold")
    rsi_overbought: float = Field(default=70.0, description="RSI overbought threshold")
    sentiment_threshold: float = Field(
        default=0.6, description="Min sentiment score to validate signals"
    )

    # --- Logging ---
    db_path: str = Field(default="data/trades.db", description="SQLite database path for audit log")
    log_level: str = Field(default="INFO", description="Logging level")

    @property
    def has_credentials(self) -> bool:
        return bool(self.coinbase_api_key and self.coinbase_api_secret)
