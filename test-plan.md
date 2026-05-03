# AI Crypto Trader — Test Plan

## What Changed
A complete autonomous AI crypto trading agent built from scratch with 5 layers: Orchestrator, Sensory Tools (market data, sentiment, indicators), Strategy (Golden Cross), Risk Management (position sizing, kill switch), and Execution & Logging (paper broker, SQLite audit). Includes PEM key normalization for Coinbase API secrets.

## What We Will Test
All testing is CLI/shell-based (no GUI). We test the primary end-to-end flow and critical safety mechanisms.

---

## Test 1: Single-Cycle Paper Mode (End-to-End Smoke Test)
**Goal:** Verify the full Scan → Analyze → Risk → Execute → Log pipeline runs without errors.

**Steps:**
1. Delete existing `data/trades.db` to start fresh
2. Run `autotrader --single-cycle --pairs BTC-USD ETH-USD`
3. Capture output

**Pass criteria:**
- Exit code is 0
- Output contains "Configuration" banner with "Mode: PAPER"
- Output contains "Scanning BTC-USD" and "Scanning ETH-USD"
- Output contains "Cycle #1 Summary" table
- Output contains both "BTC-USD" and "ETH-USD" rows with prices > $0
- Output contains "Wallet:" with balance info
- Output contains "Win rate:" and "Daily PnL:"
- `data/trades.db` file exists after run
- SQLite `decisions` table has >= 2 rows (one per pair)

**Fail criteria:**
- Any uncaught exception or non-zero exit code
- Missing pairs in summary table
- Prices showing as "N/A" or $0 (would indicate paper simulation not working)

---

## Test 2: Strategy Layer — Golden Cross BUY Signal
**Goal:** Prove the strategy produces a BUY signal when given a golden cross pattern, not just HOLD.

**Steps:**
1. Write a Python script that:
   - Creates 100 candles where the first 60 have short MA < long MA, and the last 40 have short MA > long MA (golden cross at candle ~60)
   - Passes through `TechnicalIndicatorTool.compute()`
   - Passes the snapshot through `GoldenCrossStrategy.evaluate()` with `sentiment_score=0.7` and `has_position=False`
2. Run the script

**Pass criteria:**
- `snapshot.golden_cross` is `True`
- Signal action is `BUY` (not HOLD)
- Signal confidence is >= 0.75 (golden cross base 0.80 + sentiment boost 0.10 - any adjustments)
- Signal reasoning contains "Golden Cross detected"
- Signal reasoning contains "Positive sentiment" (since 0.7 >= 0.6 threshold)

**Fail criteria:**
- Signal is HOLD or SELL
- Golden cross not detected despite crafted data
- Confidence below minimum gate (0.50)

---

## Test 3: Strategy Layer — Death Cross SELL Signal
**Goal:** Prove the strategy produces a SELL signal when holding a position and a death cross occurs.

**Steps:**
1. Same script, but create candles where short MA crosses BELOW long MA (death cross)
2. Call `GoldenCrossStrategy.evaluate()` with `has_position=True`

**Pass criteria:**
- `snapshot.death_cross` is `True`
- Signal action is `SELL`
- Signal confidence is `0.85`
- Signal reasoning contains "Death Cross detected"

**Fail criteria:**
- Signal is HOLD despite death cross pattern
- Death cross not detected

---

## Test 4: Risk Management — Position Sizing and Approval
**Goal:** Verify position sizing respects the 2% limit, stop-loss/take-profit are calculated correctly, and the confidence gate works.

**Steps:**
1. Write a Python script that:
   - Creates a RiskManager with config (max_position_pct=0.02, stop_loss=0.03, take_profit=0.06)
   - Creates a BUY signal with confidence=0.80 for BTC-USD
   - Calls `risk.evaluate(signal, wallet_balance_usd=10000, current_price=68000)`
   - Also tests with confidence=0.30 (below 0.50 gate)

**Pass criteria (high confidence):**
- `approved` is `True`
- `quantity` == 10000 * 0.02 / 68000 ≈ 0.002941
- `stop_loss` == 68000 * 0.97 = 65960.0
- `take_profit` == 68000 * 1.06 = 72080.0

**Pass criteria (low confidence):**
- `approved` is `False`
- `reason` contains "confidence" and "below minimum"

**Fail criteria:**
- Position exceeds 2% of wallet
- Stop-loss or take-profit calculated incorrectly
- Low-confidence signal gets approved

---

## Test 5: Risk Management — Kill Switch
**Goal:** Verify the kill switch activates when daily loss exceeds 5% and blocks all subsequent trades.

**Steps:**
1. Write a Python script that:
   - Creates an AuditLogger with a fresh DB
   - Inserts a daily_pnl record of -$600 (which is > 5% of $10,000 wallet)
   - Creates a RiskManager and calls `evaluate()` with a valid BUY signal
   - Checks `risk.is_killed` afterward

**Pass criteria:**
- `risk.is_killed` is `True` after evaluation
- `approved` is `False`
- `reason` contains "Kill switch" or "kill_switch"
- `decisions` table contains a "kill_switch" entry

**Fail criteria:**
- Kill switch does not activate despite exceeding loss limit
- Trade gets approved despite kill switch

---

## Test 6: Broker — Paper Trade Execution and Balance
**Goal:** Verify paper trading correctly updates balances.

**Steps:**
1. Write a Python script that:
   - Creates a BrokerTool in paper mode
   - Records initial balance (should be $10,000 USD)
   - Places a market BUY order for 0.01 BTC at $68,000
   - Checks balance after buy
   - Places a market SELL order for 0.01 BTC at $69,000
   - Checks balance after sell

**Pass criteria:**
- Initial balance: `{'USD': 10000.0}`
- After BUY: USD decreased by 0.01 * 68000 = $680, BTC balance = 0.01
- After SELL: USD increased by 0.01 * 69000 = $690, BTC balance = 0
- Net profit: $10 (690 - 680)
- Both orders return `success=True` with non-empty `order_id`

**Fail criteria:**
- Balances don't update correctly
- Orders fail in paper mode

---

## Test 7: Audit Log Persistence
**Goal:** Verify that trades and decisions are persisted to SQLite with correct schema.

**Steps:**
1. After running Test 1, query `data/trades.db`:
   - `SELECT COUNT(*) FROM decisions`
   - `SELECT * FROM decisions LIMIT 5`
   - Check schema of all 3 tables

**Pass criteria:**
- `decisions` table has rows with: id, timestamp, pair, action, reasoning, data
- `daily_pnl` table exists with correct schema
- `trades` table exists with columns: id, timestamp, pair, side, quantity, price, order_id, strategy, confidence, reasoning, stop_loss, take_profit, status
- Timestamp values are ISO format

**Fail criteria:**
- Tables missing or schema incorrect
- No rows written after single-cycle run

---

## Test 8: CLI Flags and Safety Check
**Goal:** Verify CLI flags work correctly and live mode safety gate blocks without credentials.

**Steps:**
1. Run `autotrader --single-cycle --pairs SOL-USD` — verify only SOL-USD is scanned
2. Run `autotrader --mode live --single-cycle` without valid credentials — verify it exits with error

**Pass criteria (custom pairs):**
- Output contains "Scanning SOL-USD"
- Output does NOT contain "BTC-USD" or "ETH-USD"
- Summary table shows only SOL-USD

**Pass criteria (live mode safety):**
- Exit code is non-zero (sys.exit(1))
- Output contains "ERROR" and "COINBASE_API_KEY" or "COINBASE_API_SECRET"

**Fail criteria:**
- Wrong pairs scanned
- Live mode starts without valid credentials

---

## Test 9: Sentiment Tool
**Goal:** Verify sentiment analysis returns structured data without crashing.

**Steps:**
1. Write a Python script that calls `SentimentTool().analyze("BTC")`
2. Verify return structure

**Pass criteria:**
- Returns dict with keys: score, normalized, label, headline_count, sample_headlines
- `normalized` is between 0.0 and 1.0
- `label` is one of "positive", "negative", "neutral"
- No uncaught exceptions

**Fail criteria:**
- Missing keys in response
- Normalized score outside 0-1 range
- Crash during analysis
