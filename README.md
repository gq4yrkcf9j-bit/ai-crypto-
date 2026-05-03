# AI Crypto Trader — Quantitative Trading Platform

An autonomous AI-powered crypto trading platform that connects to Coinbase Advanced Trade to execute profitable trades using machine learning, ensemble technical analysis, sentiment analysis, and fee-aware risk management.

## Architecture

The system is organized into 5 functional layers with an ML prediction engine:

### 1. The Brain (Orchestrator)
Central agent managing the continuous **Scan → Analyze → Risk Check → Execute → Log** loop.
- **Short-Term Memory**: Current open positions, recent price candles, trailing stop high-water marks
- **Long-Term Memory**: Trade history, win/loss tracking, streak detection, ML training data

### 2. Sensory Tools (Data Ingestion)
- **Market Data Tool**: Real-time OHLCV candles and ticker data from Coinbase (with paper simulation fallback)
- **Sentiment Tool**: Crypto news headline sentiment analysis (CryptoCompare + TextBlob NLP)
- **Technical Indicator Tool**: 20+ indicators including SMA, EMA, RSI, Bollinger Bands, MACD, Stochastic RSI, ADX, ATR, OBV, VWAP — with crossover detection and market regime classification

### 3. Strategy Layer (Ensemble Decision Maker)
- **Ensemble Strategy**: Combines three weighted signal sources:
  - **ML Prediction** (40%): Gradient boosting classifier trained on 17 technical features to predict price direction
  - **Technical Analysis** (40%): Multi-indicator scoring from trend, momentum, volume, and mean-reversion signals
  - **Sentiment Analysis** (20%): News-derived market fear/greed gauge
- **Fee-Aware Filtering**: Only enters trades where expected return exceeds Coinbase round-trip fees + minimum profit margin
- **Market Regime Detection**: Classifies markets as `trending_up`, `trending_down`, or `ranging` using ADX, DI+/DI-, and SMA alignment — reduces confidence in ranging markets

### 4. Risk Management Guardrail (Fee-Aware)
- **Coinbase Fee Model**: Configurable maker/taker fees (default: 0.6% taker per side, 1.2% round-trip)
- **Fee Profitability Gate**: Rejects any trade where take-profit doesn't exceed round-trip fees
- **ATR-Based Position Sizing**: Scales position size inversely with volatility (high-vol → smaller trades)
- **Trailing Stop-Loss**: Ratchets stop up as price moves favorably (locks in profit)
- **Dynamic Stop/Take-Profit**: ATR-scaled exit levels (wider in volatile markets, tighter in calm markets)
- **Kill Switch**: Shuts down trading if daily losses exceed threshold (default 5%)
- **Confidence Gate**: Rejects ensemble signals below minimum confidence

### 5. Execution & Logging
- **Broker Tool**: Places market and limit orders via Coinbase Advanced Trade API
- **Paper Trading**: Full simulation with virtual $10,000 balance and realistic fee deductions
- **Fee Tracking**: Every order records the Coinbase fee deducted, tracked in P&L calculations
- **Audit Logger**: SQLite database recording every trade, decision, fee, and ML prediction with reasoning

### ML Engine
- **Gradient Boosting Classifier**: Trained on 17 features (RSI, MACD, Stochastic, ADX, DI spread, ATR%, OBV slope, VWAP deviation, BB position, SMA/EMA spread, trend strength)
- **Online Learning**: Accumulates labeled training data from completed trades; retrains every 10 samples
- **Bootstrap Training**: Trains on historical candle data using look-ahead labels on first cycles
- **3-Class Prediction**: Up (>0.8% move), Down (<-0.8% move), Flat (within 0.8%) — threshold set above round-trip fees

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

## Configuration Parameters

### Fee Schedule

| Parameter | Default | Description |
|-----------|---------|-------------|
| `TAKER_FEE_PCT` | 0.6% | Coinbase taker fee per side |
| `MAKER_FEE_PCT` | 0.4% | Coinbase maker fee per side |

### Risk Management

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_POSITION_PCT` | 2% | Max wallet % per trade |
| `DAILY_LOSS_LIMIT_PCT` | 5% | Kill switch threshold |
| `DEFAULT_STOP_LOSS_PCT` | 3% | Stop-loss below entry |
| `DEFAULT_TAKE_PROFIT_PCT` | 6% | Take-profit above entry |
| `MIN_PROFIT_AFTER_FEES_PCT` | 0.5% | Min profit after fees to enter trade |
| `TRAILING_STOP_PCT` | 2% | Trailing stop distance from high-water mark |
| `ATR_POSITION_SCALAR` | 1.0 | Volatility-based position size scaling |

### Strategy / Ensemble

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MIN_SIGNAL_CONFIDENCE` | 0.55 | Min ensemble confidence to act |
| `ML_MODEL_WEIGHT` | 0.40 | ML model weight in ensemble |
| `TECHNICAL_WEIGHT` | 0.40 | Technical indicator weight |
| `SENTIMENT_WEIGHT` | 0.20 | Sentiment weight in ensemble |
| `SENTIMENT_THRESHOLD` | 0.6 | Min sentiment to validate buy |

## How Profitability Is Ensured

1. **Round-Trip Fee Awareness**: Every trade must clear the Coinbase round-trip fee (buy + sell = ~1.2%) plus a minimum profit margin before the system will enter
2. **ATR-Scaled Exits**: Take-profit levels are set using ATR (Average True Range), ensuring targets reflect actual market volatility — not arbitrary percentages
3. **Trailing Stops**: Once a trade moves into profit, the trailing stop ratchets up to lock in gains, preventing profitable trades from becoming losses
4. **Regime Filtering**: The system detects market regimes (trending vs ranging) and reduces confidence in ranging markets where trend-following strategies underperform
5. **ML-Validated Signals**: The ensemble requires ML, technical, and sentiment alignment — reducing false signals
6. **Volatility-Scaled Sizing**: High-volatility environments get smaller position sizes, reducing risk of large drawdowns

## Audit Log

Every trade and decision is stored in SQLite (`data/trades.db`):

```sql
-- View recent trades with fees
SELECT * FROM trades ORDER BY id DESC LIMIT 20;

-- Check daily P&L and total fees
SELECT * FROM daily_pnl ORDER BY date DESC;

-- Review decision history
SELECT * FROM decisions WHERE pair = 'BTC-USD' ORDER BY id DESC;
```

## Safety Features

- **Paper trading by default** — no real money until you explicitly switch to `--mode live`
- **Kill switch** — automatically stops trading after excessive daily losses
- **Position limits** — prevents over-concentration in any single trade
- **Loss streak detection** — avoids pairs with consecutive losses
- **Fee gate** — never enters a trade that can't be profitable after fees
- **Trailing stops** — protects profits once a trade moves favorably
