---
name: testing-autotrader
description: Test the AI crypto trading agent end-to-end in paper mode. Use when verifying orchestrator, strategy, risk management, broker, or audit logging changes.
---

# Testing the AI Crypto Trader

## Prerequisites

- Python venv at `.venv/` with `autotrader` CLI installed (`pip install -e .`)
- No GUI needed — all testing is CLI/shell-based, so **do not record**

## Devin Secrets Needed

- `COINBASE_API_KEY` — Coinbase Advanced Trade API key (optional for paper mode)
- `COINBASE_API_SECRET` — Coinbase Advanced Trade API secret / EC private key in PEM format (optional for paper mode)

> **Note:** The API secret may get corrupted during copy-paste due to Cyrillic homoglyph substitution. If the Coinbase API returns 401, the secret likely needs to be re-entered from the JSON file downloaded at https://cloud.coinbase.com/access/api. Paper mode works without valid credentials via simulation fallback.

## Quick Smoke Test

```bash
source .venv/bin/activate
rm -f data/trades.db  # fresh DB
autotrader --single-cycle --pairs BTC-USD ETH-USD
```

**Verify:**
- Exit code 0
- Banner shows "Mode: PAPER"
- Summary table shows both pairs with prices > $0
- Wallet shows `{'USD': 10000.0}`
- `data/trades.db` exists with `decisions` table rows

## Testing Strategy Signals (Golden Cross / Death Cross)

The paper mode generates random-walk candle data, so golden/death crosses are **unlikely** to occur naturally. To test signal generation deterministically, write a Python script that crafts candle data.

### Golden Cross (BUY signal)

The cross detection checks: `prev_sma_short <= prev_sma_long AND sma_short > sma_long` at the **last two** candle positions. The crossover must happen between candle N-1 and candle N.

**Working pattern (100 candles, SMA20/SMA50):**
- Candles 0-49: price = 100 (flat baseline)
- Candles 50-98: price = 95 (slight dip → SMA20 dips below SMA50)
- Candle 99: price = 105 (spike → SMA20 jumps above SMA50)

This produces: SMA20@98=95.0 <= SMA50@98=95.1, SMA20@99=95.5 > SMA50@99=95.2 → golden cross.

### Death Cross (SELL signal)

Reverse the pattern:
- Candles 0-49: price = 100
- Candles 50-98: price = 105 (slight rise)
- Candle 99: price = 95 (drop)

**Important:** Set `has_position=True` when evaluating sell signals, otherwise the strategy returns HOLD.

## Testing Risk Management

### Position Sizing
- Create a `RiskManager` with `max_position_pct=0.02`
- Pass a BUY signal with `confidence >= 0.50`
- Verify: `quantity = wallet_balance * 0.02 / current_price`

### Kill Switch
- Insert a negative `daily_pnl` record exceeding `daily_loss_limit_pct` (default 5%) of wallet
- Call `risk.evaluate()` → should activate kill switch
- Verify `risk.is_killed == True` and all subsequent trades blocked
- Check `decisions` table for `action='kill_switch'` entry

### Confidence Gate
- Signals with `confidence < 0.50` are rejected regardless of other factors

## Testing Paper Broker

- Initial balance: `{'USD': 10000.0}`
- BUY deducts `quantity * price` from USD, credits crypto
- SELL credits `quantity * price` to USD, removes crypto
- All orders return `success=True` with `order_id` prefixed `paper-`

## Testing Audit Logging

Query SQLite at `data/trades.db`:
```python
import sqlite3
conn = sqlite3.connect('data/trades.db')
conn.execute('SELECT * FROM decisions').fetchall()  # decision log
conn.execute('SELECT * FROM trades').fetchall()      # trade log
conn.execute('SELECT * FROM daily_pnl').fetchall()   # daily P&L
```

## CLI Flags

- `--single-cycle` — run one cycle and exit (essential for testing)
- `--pairs SOL-USD` — override default trading pairs
- `--mode live` — requires valid credentials or exits with error
- `--log-level DEBUG` — verbose logging

## Known Issues

- Sentiment tool may return neutral (0.5) for all assets if CryptoCompare news API has no matching headlines. This is a data availability issue, not a bug.
- PEM key normalization handles Cyrillic homoglyphs and pipe-encoded newlines but may not recover completely corrupted key data.
- `sqlite3` CLI may not be installed on the VM — use Python's `sqlite3` module instead.
