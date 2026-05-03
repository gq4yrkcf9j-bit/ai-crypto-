"""Configuration for the AI Crypto Trader."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator
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

    @field_validator("coinbase_api_secret", mode="before")
    @classmethod
    def _normalize_pem_secret(cls, v: str) -> str:
        """Normalize PEM key from environment variable.

        Handles common formatting issues:
        - Cyrillic/Unicode homoglyphs → ASCII equivalents
        - Stray characters (pipes, spaces, hyphens in base64 body)
        - Literal ``\\n`` → real newlines
        - Reconstructs a clean PEM via DER re-serialization
        """
        import base64
        import re

        if not isinstance(v, str) or not v:
            return v

        # Map Cyrillic look-alikes to ASCII (common copy-paste issue)
        _HOMOGLYPHS: dict[str, str] = {
            "\u0410": "A",
            "\u0412": "B",
            "\u0421": "C",
            "\u0415": "E",
            "\u041d": "H",
            "\u0406": "I",
            "\u041a": "K",
            "\u041c": "M",
            "\u041e": "O",
            "\u0420": "P",
            "\u0422": "T",
            "\u0425": "X",
            "\u0430": "a",
            "\u0435": "e",
            "\u043e": "o",
            "\u0440": "p",
            "\u0441": "c",
            "\u0445": "x",
            "\u0443": "y",
            "\u0456": "i",
        }
        for cyrillic, latin in _HOMOGLYPHS.items():
            v = v.replace(cyrillic, latin)
        v = v.replace("|", "")
        v = v.replace("\\n", "\n")

        begin_match = re.search(
            r"-----BEGIN (EC PRIVATE KEY|PRIVATE KEY)-----",
            v,
        )
        end_match = re.search(
            r"-----END (EC PRIVATE KEY|PRIVATE KEY)-----",
            v,
        )
        if not (begin_match and end_match):
            return v

        body_start = begin_match.end()
        body_end = end_match.start()
        raw_body = v[body_start:body_end]
        # Keep only valid base64 characters
        clean_body = re.sub(r"[^A-Za-z0-9+/=]", "", raw_body)

        # Remove stray 'n' artifacts from pipe-encoded newlines.
        # Original PEM newlines may have been stored as "|n"; after removing
        # "|", orphan "n" chars remain at PEM line-break boundaries (every
        # 64 base64 chars) and at the start/end of the body.
        if clean_body.startswith("n"):
            clean_body = clean_body[1:]
        if clean_body.endswith("n"):
            clean_body = clean_body[:-1]
        # Interior break artifacts at 64-char intervals
        result_chars: list[str] = []
        pos = 0
        for ch in clean_body:
            if pos > 0 and pos % 64 == 0 and ch == "n":
                continue  # skip artifact
            result_chars.append(ch)
            pos += 1
        clean_body = "".join(result_chars)

        # Fix base64 padding
        clean_body = clean_body.rstrip("=")
        pad = (4 - len(clean_body) % 4) % 4
        clean_body += "=" * pad

        # Try to reconstruct via DER → cryptography → clean PEM
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                NoEncryption,
                PrivateFormat,
            )

            der = base64.b64decode(clean_body)
            # Extract private key integer from DER
            # SEC1 format: SEQUENCE { INTEGER(1), OCTET STRING(privkey), ... }
            if der[0] == 0x30 and der[5] == 0x04:
                key_len = der[6]
                priv_bytes = der[7 : 7 + key_len]
                priv_int = int.from_bytes(priv_bytes, "big")
                key = ec.derive_private_key(priv_int, ec.SECP256R1())
                pem_bytes = key.private_bytes(
                    Encoding.PEM,
                    PrivateFormat.TraditionalOpenSSL,
                    NoEncryption(),
                )
                return pem_bytes.decode()
        except Exception:
            pass

        # Fallback: return manually wrapped PEM
        wrapped = "\n".join(clean_body[i : i + 64] for i in range(0, len(clean_body), 64))
        key_type = begin_match.group(1)
        return f"-----BEGIN {key_type}-----\n{wrapped}\n-----END {key_type}-----\n"

    # --- Trading Parameters ---
    trading_mode: TradingMode = Field(default=TradingMode.PAPER, description="paper or live")
    trading_pairs: list[str] = Field(
        default=["BTC-USD", "ETH-USD"], description="Crypto pairs to trade"
    )
    scan_interval_seconds: int = Field(default=60, description="Seconds between scan cycles")

    # --- Coinbase Fee Schedule (maker/taker by 30-day volume tier) ---
    # Defaults are the lowest tier ($0-$10K). Adjust to your actual tier.
    taker_fee_pct: float = Field(
        default=0.006, description="Taker fee as decimal (0.6% = 0.006)"
    )
    maker_fee_pct: float = Field(
        default=0.004, description="Maker fee as decimal (0.4% = 0.004)"
    )

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
    min_profit_after_fees_pct: float = Field(
        default=0.005, description="Min expected profit after fees to enter trade (0.5%)"
    )
    trailing_stop_pct: float = Field(
        default=0.02, description="Trailing stop-loss distance (2% below high-water mark)"
    )
    atr_position_scalar: float = Field(
        default=1.0, description="Scale position size inversely with ATR volatility"
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
    min_signal_confidence: float = Field(
        default=0.55, description="Min ensemble confidence to act"
    )
    ml_model_weight: float = Field(
        default=0.40, description="Weight of ML model in ensemble signal (0-1)"
    )
    technical_weight: float = Field(
        default=0.40, description="Weight of technical signals in ensemble (0-1)"
    )
    sentiment_weight: float = Field(
        default=0.20, description="Weight of sentiment in ensemble signal (0-1)"
    )

    # --- Logging ---
    db_path: str = Field(default="data/trades.db", description="SQLite database path for audit log")
    log_level: str = Field(default="INFO", description="Logging level")

    @property
    def has_credentials(self) -> bool:
        return bool(self.coinbase_api_key and self.coinbase_api_secret)

    @property
    def round_trip_fee_pct(self) -> float:
        """Total round-trip fee: buy-side taker + sell-side taker."""
        return self.taker_fee_pct * 2
