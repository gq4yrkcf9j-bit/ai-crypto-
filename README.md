# AI Crypto Trader

An autonomous AI-powered crypto trading agent that connects to Coinbase Advanced Trade to execute trades using technical analysis, sentiment analysis, and risk management.

## Architecture

The system is organized into 5 functional layers:

### 1. The Brain (Orchestrator)
Central agent managing the continuous **Scan → Analyze → Risk Check → Execute → Log** loop.
- **Short-Term Memory**: Current open positions, recent price candles
- **Long-Term Memory**: Trade history, win/loss tracking, streak detection

### 2. Sensory Tools (Data Ingestion)
- **Market Data Tool**: Real-time price candles and ticker data from Coinbase
- **Sentiment Tool**: Crypto news headline sentiment analysis (CryptoCompare + TextBlob NLP)
- **Technical Indicator Tool**: SMA, EMA, RSI, Bollinger Bands with crossover detection

### 3. Strategy Layer (Decision Maker)
- **Golden Cross Strategy**: Detects MA crossovers validated by sentiment and RSI
- Produces trade signals with confidence scores and reasoning
- Extensible base class for adding new strategies

### 4. Risk Management Guardrail
- **Position Sizing**: No single trade exceeds 2% of wallet balance (configurable)
- **Stop-Loss / Take-Profit**: Automatically calculated and attached to every order
- **Kill Switch**: Shuts down trading if daily losses exceed threshold (default 5%)
- **Confidence Gate**: Rejects signals below minimum confidence

### 5. Execution & Logging
- **Broker Tool**: Places market and limit orders via Coinbase Advanced Trade API
- **Paper Trading**: Full simulation mode with virtual $10,000 balance
- **Audit Logger**: SQLite database recording every trade and decision with reasoning

## Quick Start

### Prerequisites
- Python 3.11+
- Coinbase Advanced Trade API key ([create one here](https://www.coinbase.com/settings/api))

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd ai-crypto-trader

# Install dependencies
pip install -e .
```

### Configuration

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your credentials
# COINBASE_API_KEY=your_key
# COINBASE_API_SECRET=your_secret
```

Or set environment variables directly:

```bash
export COINBASE_API_KEY=your_key
export COINBASE_API_SECRET=your_secret
```

### Running

```bash
# Paper trading mode (default — no real money)
autotrader

# Run a single scan cycle (great for testing)
autotrader --single-cycle

# Specify pairs and interval
autotrader --pairs BTC-USD ETH-USD SOL-USD --interval 30

# Live trading (requires API credentials)
autotrader --mode live

# Debug logging
autotrader --log-level DEBUG
```

## CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `--mode` | `paper` or `live` | `paper` |
| `--pairs` | Trading pairs (space-separated) | `BTC-USD ETH-USD` |
| `--interval` | Scan interval in seconds | `60` |
| `--single-cycle` | Run one cycle and exit | `false` |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

## Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_POSITION_PCT` | 2% | Max wallet % per trade |
| `DAILY_LOSS_LIMIT_PCT` | 5% | Kill switch threshold |
| `DEFAULT_STOP_LOSS_PCT` | 3% | Stop-loss below entry |
| `DEFAULT_TAKE_PROFIT_PCT` | 6% | Take-profit above entry |
| `SENTIMENT_THRESHOLD` | 0.6 | Min sentiment to validate buy |

## Strategy: Golden Cross

The default strategy combines multiple signals:

**Buy Conditions:**
1. Short-term MA crosses above long-term MA (Golden Cross)
2. Sentiment score ≥ threshold (positive news)
3. RSI oversold adds confidence boost
4. Price near lower Bollinger Band (oversold bounce)

**Sell Conditions:**
1. Death Cross (short MA crosses below long MA)
2. RSI overbought (take profit)
3. Price above upper Bollinger Band (reversal risk)

**Automatic Exits:**
- Stop-loss triggers at configured % below entry
- Take-profit triggers at configured % above entry

## Adding New Strategies

Extend `BaseStrategy` and implement the `evaluate` method:

```python
from autotrader.strategy.base import BaseStrategy
from autotrader.strategy.signals import TradeSignal

class MyStrategy(BaseStrategy):
    name = "my_strategy"

    def evaluate(self, pair, snapshot, sentiment_score, has_position):
        # Your logic here
        return TradeSignal(...)
```

## Audit Log

Every trade and decision is stored in SQLite (`data/trades.db`):

```sql
-- View recent trades
SELECT * FROM trades ORDER BY id DESC LIMIT 20;

-- Check daily P&L
SELECT * FROM daily_pnl ORDER BY date DESC;

-- Review decision history
SELECT * FROM decisions WHERE pair = 'BTC-USD' ORDER BY id DESC;
```

## Safety Features

- **Paper trading by default** — no real money until you explicitly switch to `--mode live`
- **Kill switch** — automatically stops trading after excessive daily losses
- **Position limits** — prevents over-concentration in any single trade
- **Loss streak detection** — avoids pairs with consecutive losses
- **Full audit trail** — every decision logged with reasoning for review

## ⚠️ Disclaimer

This software is for educational and informational purposes. Cryptocurrency trading carries significant risk. Past performance does not guarantee future results. Always start with paper trading and only risk what you can afford to lose.
