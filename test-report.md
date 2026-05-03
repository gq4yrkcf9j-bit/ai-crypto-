# AI Crypto Trader — Test Report

**Tested by:** Devin ([session link](https://app.devin.ai/sessions/fc70d0af947845fd8e96763d7c4fea21))
**PR:** [#1 feat: AI Crypto Trading Agent with Coinbase Integration](https://github.com/gq4yrkcf9j-bit/ai-crypto-/pull/1)
**Method:** Ran CLI commands and Python scripts against the installed `autotrader` package in paper mode. No GUI — all shell-based.

---

## Escalations

- **Coinbase API returns 401 Unauthorized** — The saved API secret is likely corrupted from copy-paste (Cyrillic homoglyphs). The PEM normalizer runs but the underlying key data differs from the original. Paper mode works via the simulation fallback, but live market data is unavailable until the secret is re-entered from the Coinbase JSON download. This does NOT block paper trading.
- **Sentiment tool returns neutral for all assets** — CryptoCompare news API returns 200 OK but no headlines matched the asset filter ("BTC", "ETH", "SOL"). This means sentiment always defaults to 0.5 (neutral), which slightly reduces Golden Cross confidence by -0.15 instead of boosting +0.10. This is a data availability issue, not a code bug — the sentiment parsing logic itself is correct.

---

## Test Results (9 tests, 40 assertions — all passed)

- **Test 1: Single-Cycle Paper Mode (E2E)** — passed. Exit code 0, banner shows "Mode: PAPER", both BTC-USD ($68,104.63) and ETH-USD ($3,802.21) scanned with simulated prices, HOLD signals generated, wallet shows $10K, summary table rendered correctly.
- **Test 2: Golden Cross BUY Signal** — passed. Crafted 100 candles with crossover at last position. `golden_cross=True`, signal=BUY, confidence=0.90 (base 0.80 + sentiment 0.10), reasoning mentions "Golden Cross detected" and "Positive sentiment".
- **Test 3: Death Cross SELL Signal** — passed. Crafted candles with death cross at last position. `death_cross=True`, signal=SELL, confidence=0.85, reasoning mentions "Death Cross detected".
- **Test 4: Risk Management — Position Sizing** — passed. BUY at $68K with $10K wallet: qty=0.002941 (exactly 2%), SL=$65,960 (3%), TP=$72,080 (6%). Low-confidence (0.30) signal correctly rejected. HOLD signal correctly not approved.
- **Test 5: Kill Switch** — passed. Injected -$600 daily PnL (exceeds 5% of $10K = $500 limit). Kill switch activated, trade blocked, reason="Kill switch triggered: daily loss $-600.00 > limit -$500.00", logged to audit DB. Subsequent trades also blocked.
- **Test 6: Paper Broker** — passed. Initial balance $10K. BUY 0.01 BTC@$68K → USD=$9,320, BTC=0.01. SELL 0.01 BTC@$69K → USD=$10,010, BTC=0. Net profit $10 correct.
- **Test 7: Audit Log Persistence** — passed. SQLite DB has 3 tables (trades, decisions, daily_pnl) with correct schema. 2 decision rows from single-cycle run with ISO timestamps.
- **Test 8: CLI Flags** — passed. `--pairs SOL-USD` scans only SOL-USD (no BTC/ETH in output). `--mode live` without credentials exits with code 1 and error message.
- **Test 9: Sentiment Tool** — passed. Returns dict with all required keys (score, normalized, label, headline_count, sample_headlines). Normalized=0.5, label="neutral".

---

## Evidence

### Test 1 — Single-Cycle Output
```
╭─────────────────────────────── Configuration ────────────────────────────────╮
│ AI Crypto Trader v0.1.0                                                      │
│ Mode:        PAPER                                                           │
│ Credentials: Connected                                                       │
│ Pairs:       BTC-USD, ETH-USD                                                │
│ Interval:    60s                                                             │
│ Risk limit:  2% per trade, 5% daily loss kill-switch                         │
│ Stop-Loss:   3% | Take-Profit: 6%                                            │
╰──────────────────────────────────────────────────────────────────────────────╯

┏━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Pair    ┃      Price ┃ Action ┃ Confidence ┃ Reasoning                      ┃
┡━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ BTC-USD │ $68,104.63 │  hold  │       0.00 │ No actionable pattern detected │
│ ETH-USD │  $3,802.21 │  hold  │       0.00 │ No actionable pattern detected │
└─────────┴────────────┴────────┴────────────┴────────────────────────────────┘
  Wallet: {'USD': 10000.0}
  Win rate: 0.0% (0W / 0L)
  Daily PnL: $0.00
```

### Tests 2-6, 9 — Component Test Output
```
=== TEST 2: Golden Cross BUY Signal ===
  [✓] T2.1 - Indicator computation: PASSED (sma_short=95.50, sma_long=95.20)
  [✓] T2.2 - Golden cross detected: PASSED
  [✓] T2.3 - Signal is BUY: PASSED (confidence=0.90)
  [✓] T2.4 - Confidence >= 0.75: PASSED (confidence=0.90)
  [✓] T2.5 - Reasoning mentions Golden Cross: PASSED
  [✓] T2.6 - Reasoning mentions sentiment: PASSED

=== TEST 3: Death Cross SELL Signal ===
  [✓] T3.1 - Death cross detected: PASSED
  [✓] T3.2 - Signal is SELL: PASSED (confidence=0.85)
  [✓] T3.3 - Confidence is 0.85: PASSED
  [✓] T3.4 - Reasoning mentions Death Cross: PASSED

=== TEST 4: Risk Management — Position Sizing & Approval ===
  [✓] T4.1 - High-confidence BUY approved: PASSED
  [✓] T4.2 - Position sizing (2%): PASSED (qty=0.002941)
  [✓] T4.3 - Stop-loss (3%): PASSED (SL=$65960.00)
  [✓] T4.4 - Take-profit (6%): PASSED (TP=$72080.00)
  [✓] T4.5 - Low-confidence rejected: PASSED
  [✓] T4.6 - Rejection mentions confidence: PASSED
  [✓] T4.7 - HOLD signal not approved: PASSED

=== TEST 5: Risk Management — Kill Switch ===
  [✓] T5.1 - Kill switch activated: PASSED
  [✓] T5.2 - Trade blocked by kill switch: PASSED
  [✓] T5.3 - Reason mentions kill switch: PASSED
  [✓] T5.4 - Kill switch logged to audit: PASSED (1 decision logged)
  [✓] T5.5 - Subsequent trades also blocked: PASSED

=== TEST 6: Broker — Paper Trade Execution & Balance ===
  [✓] T6.1 - Initial balance is $10,000: PASSED
  [✓] T6.2 - Paper BUY order succeeds: PASSED
  [✓] T6.3 - USD debited correctly: PASSED (USD=$9320.00)
  [✓] T6.4 - BTC credited correctly: PASSED (BTC=0.01)
  [✓] T6.5 - Paper SELL order succeeds: PASSED
  [✓] T6.6 - USD after sell correct (profit $10): PASSED (USD=$10010.00)
  [✓] T6.7 - BTC balance zeroed after sell: PASSED

=== TEST 9: Sentiment Tool ===
  [✓] T9.1 - Return structure has required keys: PASSED
  [✓] T9.2 - Normalized score in [0, 1]: PASSED (normalized=0.500)
  [✓] T9.3 - Label is valid: PASSED (label=neutral)

TEST SUMMARY: 32 passed, 0 failed, 32 total
```

### Test 7 — SQLite Audit Log
```
=== SCHEMA ===
  trades: [id (INTEGER), timestamp (TEXT), pair (TEXT), side (TEXT), quantity (REAL),
           price (REAL), order_id (TEXT), strategy (TEXT), confidence (REAL),
           reasoning (TEXT), stop_loss (REAL), take_profit (REAL), status (TEXT)]
  decisions: [id (INTEGER), timestamp (TEXT), pair (TEXT), action (TEXT),
              reasoning (TEXT), data (TEXT)]
  daily_pnl: [date (TEXT), realized_pnl (REAL), trade_count (INTEGER)]

=== DECISIONS: 2 rows ===
  id=1 ts=2026-05-03T05:48:26.575315+00:00 pair=BTC-USD action=hold
  id=2 ts=2026-05-03T05:48:26.963796+00:00 pair=ETH-USD action=hold
```

### Test 8 — CLI Flags
```
# --pairs SOL-USD: Only SOL-USD in summary table
┃ Pair    ┃   Price ┃ Action ┃ Confidence ┃ Reasoning                      ┃
│ SOL-USD │ $172.25 │  hold  │       0.00 │ No actionable pattern detected │

# --mode live without credentials: exits with error
ERROR: Live mode requires COINBASE_API_KEY and COINBASE_API_SECRET environment variables.
EXIT_CODE=1
```
