"""Adversarial test script for AI Crypto Trader components."""
import json
import math
import os
import sys
import tempfile

# Ensure the src directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from autotrader.config import Config, TradingMode
from autotrader.logging.audit import AuditLogger
from autotrader.risk.manager import RiskManager
from autotrader.strategy.golden_cross import GoldenCrossStrategy
from autotrader.strategy.signals import SignalAction, TradeSignal
from autotrader.tools.broker import BrokerTool
from autotrader.tools.indicators import TechnicalIndicatorTool
from autotrader.tools.sentiment import SentimentTool

PASS = "PASSED"
FAIL = "FAILED"
results = []


def report(test_name: str, status: str, detail: str = ""):
    results.append((test_name, status, detail))
    marker = "✓" if status == PASS else "✗"
    print(f"  [{marker}] {test_name}: {status}")
    if detail:
        print(f"      {detail}")


# ===================================================================
# TEST 2: Golden Cross BUY Signal
# ===================================================================
print("\n=== TEST 2: Golden Cross BUY Signal ===")

# Craft candle data that guarantees a golden cross at the LAST candle.
# The cross detection checks: prev_sma_short <= prev_sma_long AND sma_short > sma_long
# So the crossover must happen between candle 98 and candle 99.
#
# Design:
#   Candles 0-49:  price = 100  (establishes SMA50 baseline)
#   Candles 50-98: price = 95   (slight dip → SMA20 dips below SMA50)
#   Candle 99:     price = 105  (spike → SMA20 jumps above SMA50)
#
# At candle 98: SMA20 = 95.0, SMA50 = 95.1 → SMA20 <= SMA50 ✓
# At candle 99: SMA20 = 95.5, SMA50 = 95.2 → SMA20 > SMA50  ✓  → golden cross!
candles_golden = []
for i in range(100):
    if i < 50:
        price = 100.0
    elif i < 99:
        price = 95.0
    else:
        price = 105.0
    candles_golden.append({
        "open": price,
        "high": price + 0.5,
        "low": price - 0.5,
        "close": price,
        "volume": 100.0,
    })

indicator_tool = TechnicalIndicatorTool(short_period=20, long_period=50, rsi_period=14)
snapshot = indicator_tool.compute("BTC-USD", candles_golden)

if snapshot is None:
    report("T2.1 - Indicator computation", FAIL, "snapshot is None")
else:
    report("T2.1 - Indicator computation", PASS, f"sma_short={snapshot.sma_short:.2f}, sma_long={snapshot.sma_long:.2f}")

    if snapshot.golden_cross:
        report("T2.2 - Golden cross detected", PASS)
    else:
        report("T2.2 - Golden cross detected", FAIL,
               f"golden_cross=False (sma_short={snapshot.sma_short:.2f} vs sma_long={snapshot.sma_long:.2f})")

    strategy = GoldenCrossStrategy(sentiment_threshold=0.6)
    signal = strategy.evaluate("BTC-USD", snapshot, sentiment_score=0.7, has_position=False)

    if signal.action == SignalAction.BUY:
        report("T2.3 - Signal is BUY", PASS, f"confidence={signal.confidence:.2f}")
    else:
        report("T2.3 - Signal is BUY", FAIL, f"action={signal.action.value}, confidence={signal.confidence:.2f}")

    if signal.confidence >= 0.75:
        report("T2.4 - Confidence >= 0.75", PASS, f"confidence={signal.confidence:.2f}")
    else:
        report("T2.4 - Confidence >= 0.75", FAIL, f"confidence={signal.confidence:.2f}")

    if "Golden Cross" in signal.reasoning:
        report("T2.5 - Reasoning mentions Golden Cross", PASS)
    else:
        report("T2.5 - Reasoning mentions Golden Cross", FAIL, f"reasoning={signal.reasoning}")

    if "sentiment" in signal.reasoning.lower():
        report("T2.6 - Reasoning mentions sentiment", PASS)
    else:
        report("T2.6 - Reasoning mentions sentiment", FAIL, f"reasoning={signal.reasoning}")


# ===================================================================
# TEST 3: Death Cross SELL Signal
# ===================================================================
print("\n=== TEST 3: Death Cross SELL Signal ===")

# Craft candle data that guarantees a death cross at the LAST candle.
# Design:
#   Candles 0-49:  price = 100  (establishes SMA50 baseline)
#   Candles 50-98: price = 105  (slight rise → SMA20 above SMA50)
#   Candle 99:     price = 95   (drop → SMA20 falls below SMA50)
#
# At candle 98: SMA20 = 105.0, SMA50 = 104.9 → SMA20 >= SMA50 ✓
# At candle 99: SMA20 = 104.5, SMA50 = 104.8 → SMA20 < SMA50  ✓  → death cross!
candles_death = []
for i in range(100):
    if i < 50:
        price = 100.0
    elif i < 99:
        price = 105.0
    else:
        price = 95.0
    candles_death.append({
        "open": price,
        "high": price + 0.5,
        "low": price - 0.5,
        "close": price,
        "volume": 100.0,
    })

snapshot_death = indicator_tool.compute("BTC-USD", candles_death)

if snapshot_death is None:
    report("T3.1 - Death cross indicator computation", FAIL, "snapshot is None")
else:
    if snapshot_death.death_cross:
        report("T3.1 - Death cross detected", PASS)
    else:
        report("T3.1 - Death cross detected", FAIL,
               f"death_cross=False (sma_short={snapshot_death.sma_short:.2f} vs sma_long={snapshot_death.sma_long:.2f})")

    signal_sell = strategy.evaluate("BTC-USD", snapshot_death, sentiment_score=0.3, has_position=True)

    if signal_sell.action == SignalAction.SELL:
        report("T3.2 - Signal is SELL", PASS, f"confidence={signal_sell.confidence:.2f}")
    else:
        report("T3.2 - Signal is SELL", FAIL, f"action={signal_sell.action.value}")

    if signal_sell.confidence == 0.85:
        report("T3.3 - Confidence is 0.85", PASS)
    else:
        report("T3.3 - Confidence is 0.85", FAIL, f"confidence={signal_sell.confidence:.2f}")

    if "Death Cross" in signal_sell.reasoning:
        report("T3.4 - Reasoning mentions Death Cross", PASS)
    else:
        report("T3.4 - Reasoning mentions Death Cross", FAIL, f"reasoning={signal_sell.reasoning}")


# ===================================================================
# TEST 4: Risk Management — Position Sizing & Approval
# ===================================================================
print("\n=== TEST 4: Risk Management — Position Sizing & Approval ===")

# Create a temp DB for risk manager
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    temp_db = f.name

try:
    os.environ["TRADING_MODE"] = "paper"
    os.environ.pop("COINBASE_API_KEY", None)
    os.environ.pop("COINBASE_API_SECRET", None)

    config = Config(
        trading_mode=TradingMode.PAPER,
        coinbase_api_key="",
        coinbase_api_secret="",
        max_position_pct=0.02,
        default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
        daily_loss_limit_pct=0.05,
        db_path=temp_db,
    )
    audit = AuditLogger(temp_db)
    risk = RiskManager(config, audit)

    # High confidence BUY signal
    buy_signal = TradeSignal(
        pair="BTC-USD",
        action=SignalAction.BUY,
        confidence=0.80,
        strategy="golden_cross",
        reasoning="Test signal",
    )

    decision = risk.evaluate(buy_signal, wallet_balance_usd=10000.0, current_price=68000.0)

    if decision.approved:
        report("T4.1 - High-confidence BUY approved", PASS)
    else:
        report("T4.1 - High-confidence BUY approved", FAIL, f"reason={decision.reason}")

    expected_qty = 10000.0 * 0.02 / 68000.0
    if abs(decision.quantity - expected_qty) < 0.000001:
        report("T4.2 - Position sizing (2%)", PASS, f"qty={decision.quantity:.6f} (expected {expected_qty:.6f})")
    else:
        report("T4.2 - Position sizing (2%)", FAIL, f"qty={decision.quantity:.6f} (expected {expected_qty:.6f})")

    expected_sl = 68000.0 * 0.97
    if abs(decision.stop_loss - expected_sl) < 0.01:
        report("T4.3 - Stop-loss (3%)", PASS, f"SL=${decision.stop_loss:.2f} (expected ${expected_sl:.2f})")
    else:
        report("T4.3 - Stop-loss (3%)", FAIL, f"SL=${decision.stop_loss:.2f} (expected ${expected_sl:.2f})")

    expected_tp = 68000.0 * 1.06
    if abs(decision.take_profit - expected_tp) < 0.01:
        report("T4.4 - Take-profit (6%)", PASS, f"TP=${decision.take_profit:.2f} (expected ${expected_tp:.2f})")
    else:
        report("T4.4 - Take-profit (6%)", FAIL, f"TP=${decision.take_profit:.2f} (expected ${expected_tp:.2f})")

    # Low confidence signal — should be rejected
    low_signal = TradeSignal(
        pair="BTC-USD",
        action=SignalAction.BUY,
        confidence=0.30,
        strategy="golden_cross",
        reasoning="Low confidence test",
    )
    low_decision = risk.evaluate(low_signal, wallet_balance_usd=10000.0, current_price=68000.0)

    if not low_decision.approved:
        report("T4.5 - Low-confidence rejected", PASS, f"reason={low_decision.reason}")
    else:
        report("T4.5 - Low-confidence rejected", FAIL, "Was approved despite confidence=0.30")

    if "confidence" in low_decision.reason.lower():
        report("T4.6 - Rejection mentions confidence", PASS)
    else:
        report("T4.6 - Rejection mentions confidence", FAIL, f"reason={low_decision.reason}")

    # HOLD signal — should not be approved
    hold_signal = TradeSignal(
        pair="BTC-USD",
        action=SignalAction.HOLD,
        confidence=0.0,
        strategy="golden_cross",
        reasoning="No pattern",
    )
    hold_decision = risk.evaluate(hold_signal, wallet_balance_usd=10000.0, current_price=68000.0)
    if not hold_decision.approved:
        report("T4.7 - HOLD signal not approved", PASS)
    else:
        report("T4.7 - HOLD signal not approved", FAIL, "HOLD was approved")

finally:
    os.unlink(temp_db)


# ===================================================================
# TEST 5: Kill Switch
# ===================================================================
print("\n=== TEST 5: Risk Management — Kill Switch ===")

with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    temp_db2 = f.name

try:
    audit2 = AuditLogger(temp_db2)
    # Insert a daily PnL of -$600 (exceeds 5% of $10,000 = $500 limit)
    audit2.update_daily_pnl(-600.0)

    config2 = Config(
        trading_mode=TradingMode.PAPER,
        coinbase_api_key="",
        coinbase_api_secret="",
        max_position_pct=0.02,
        default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
        daily_loss_limit_pct=0.05,
        db_path=temp_db2,
    )
    risk2 = RiskManager(config2, audit2)

    kill_signal = TradeSignal(
        pair="BTC-USD",
        action=SignalAction.BUY,
        confidence=0.90,
        strategy="golden_cross",
        reasoning="Kill switch test",
    )
    kill_decision = risk2.evaluate(kill_signal, wallet_balance_usd=10000.0, current_price=68000.0)

    if risk2.is_killed:
        report("T5.1 - Kill switch activated", PASS)
    else:
        report("T5.1 - Kill switch activated", FAIL, "is_killed=False")

    if not kill_decision.approved:
        report("T5.2 - Trade blocked by kill switch", PASS)
    else:
        report("T5.2 - Trade blocked by kill switch", FAIL, "Trade was approved despite kill switch")

    if "kill" in kill_decision.reason.lower():
        report("T5.3 - Reason mentions kill switch", PASS, f"reason={kill_decision.reason}")
    else:
        report("T5.3 - Reason mentions kill switch", FAIL, f"reason={kill_decision.reason}")

    # Verify audit log has kill_switch entry
    import sqlite3
    conn = sqlite3.connect(temp_db2)
    rows = conn.execute("SELECT * FROM decisions WHERE action='kill_switch'").fetchall()
    if len(rows) > 0:
        report("T5.4 - Kill switch logged to audit", PASS, f"{len(rows)} decision(s) logged")
    else:
        report("T5.4 - Kill switch logged to audit", FAIL, "No kill_switch decisions in DB")

    # Second trade should also be blocked
    kill_decision2 = risk2.evaluate(kill_signal, wallet_balance_usd=10000.0, current_price=68000.0)
    if not kill_decision2.approved and "kill" in kill_decision2.reason.lower():
        report("T5.5 - Subsequent trades also blocked", PASS)
    else:
        report("T5.5 - Subsequent trades also blocked", FAIL, f"approved={kill_decision2.approved}")

    conn.close()
finally:
    os.unlink(temp_db2)


# ===================================================================
# TEST 6: Paper Broker Execution & Balance
# ===================================================================
print("\n=== TEST 6: Broker — Paper Trade Execution & Balance ===")

config_paper = Config(
    trading_mode=TradingMode.PAPER,
    coinbase_api_key="",
    coinbase_api_secret="",
    db_path=":memory:",
)
broker = BrokerTool(config_paper)

initial = broker.get_wallet_balance()
if initial == {"USD": 10000.0}:
    report("T6.1 - Initial balance is $10,000", PASS, f"balance={initial}")
else:
    report("T6.1 - Initial balance is $10,000", FAIL, f"balance={initial}")

# BUY 0.01 BTC at $68,000
buy_result = broker.place_market_order("BTC-USD", "buy", 0.01, 68000.0)
if buy_result.success:
    report("T6.2 - Paper BUY order succeeds", PASS, f"order_id={buy_result.order_id}")
else:
    report("T6.2 - Paper BUY order succeeds", FAIL, f"message={buy_result.message}")

after_buy = broker.get_wallet_balance()
expected_usd_after_buy = 10000.0 - (0.01 * 68000.0)  # $9,320
btc_balance = after_buy.get("BTC", 0)
usd_after = after_buy.get("USD", 0)

if abs(usd_after - expected_usd_after_buy) < 0.01:
    report("T6.3 - USD debited correctly", PASS, f"USD=${usd_after:.2f} (expected ${expected_usd_after_buy:.2f})")
else:
    report("T6.3 - USD debited correctly", FAIL, f"USD=${usd_after:.2f} (expected ${expected_usd_after_buy:.2f})")

if abs(btc_balance - 0.01) < 0.000001:
    report("T6.4 - BTC credited correctly", PASS, f"BTC={btc_balance}")
else:
    report("T6.4 - BTC credited correctly", FAIL, f"BTC={btc_balance}")

# SELL 0.01 BTC at $69,000
sell_result = broker.place_market_order("BTC-USD", "sell", 0.01, 69000.0)
if sell_result.success:
    report("T6.5 - Paper SELL order succeeds", PASS, f"order_id={sell_result.order_id}")
else:
    report("T6.5 - Paper SELL order succeeds", FAIL, f"message={sell_result.message}")

after_sell = broker.get_wallet_balance()
expected_usd_final = expected_usd_after_buy + (0.01 * 69000.0)  # $10,010
usd_final = after_sell.get("USD", 0)
btc_final = after_sell.get("BTC", 0)

if abs(usd_final - expected_usd_final) < 0.01:
    report("T6.6 - USD after sell correct (profit $10)", PASS, f"USD=${usd_final:.2f} (expected ${expected_usd_final:.2f})")
else:
    report("T6.6 - USD after sell correct (profit $10)", FAIL, f"USD=${usd_final:.2f} (expected ${expected_usd_final:.2f})")

if btc_final == 0 or btc_final < 0.000001:
    report("T6.7 - BTC balance zeroed after sell", PASS, f"BTC={btc_final}")
else:
    report("T6.7 - BTC balance zeroed after sell", FAIL, f"BTC={btc_final}")


# ===================================================================
# TEST 9: Sentiment Tool
# ===================================================================
print("\n=== TEST 9: Sentiment Tool ===")

sentiment = SentimentTool()
result_sent = sentiment.analyze("BTC")

required_keys = {"score", "normalized", "label", "headline_count", "sample_headlines"}
if required_keys.issubset(result_sent.keys()):
    report("T9.1 - Return structure has required keys", PASS, f"keys={list(result_sent.keys())}")
else:
    missing = required_keys - set(result_sent.keys())
    report("T9.1 - Return structure has required keys", FAIL, f"missing={missing}")

norm = result_sent.get("normalized", -1)
if 0.0 <= norm <= 1.0:
    report("T9.2 - Normalized score in [0, 1]", PASS, f"normalized={norm:.3f}")
else:
    report("T9.2 - Normalized score in [0, 1]", FAIL, f"normalized={norm}")

label = result_sent.get("label", "")
if label in ("positive", "negative", "neutral"):
    report("T9.3 - Label is valid", PASS, f"label={label}")
else:
    report("T9.3 - Label is valid", FAIL, f"label={label}")


# ===================================================================
# SUMMARY
# ===================================================================
print("\n" + "=" * 60)
print("TEST SUMMARY")
print("=" * 60)
passed = sum(1 for _, s, _ in results if s == PASS)
failed = sum(1 for _, s, _ in results if s == FAIL)
print(f"  {passed} passed, {failed} failed, {len(results)} total")
if failed > 0:
    print("\n  FAILURES:")
    for name, status, detail in results:
        if status == FAIL:
            print(f"    - {name}: {detail}")

sys.exit(0 if failed == 0 else 1)
