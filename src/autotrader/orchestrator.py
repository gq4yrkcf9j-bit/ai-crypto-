"""The Brain — central orchestrator that runs the Scan → Analyze → Risk → Execute → Log loop.

Uses ensemble strategy (ML + technical + sentiment), fee-aware risk management,
trailing stop-losses, and adaptive position sizing.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from rich.console import Console
from rich.table import Table

from autotrader.config import Config
from autotrader.logging.audit import AuditLogger
from autotrader.memory.store import MemoryStore, Position
from autotrader.ml.predictor import MLPredictor
from autotrader.risk.manager import RiskManager
from autotrader.strategy.ensemble import EnsembleStrategy
from autotrader.strategy.signals import SignalAction, TradeSignal
from autotrader.tools.broker import BrokerTool
from autotrader.tools.indicators import IndicatorSnapshot, TechnicalIndicatorTool
from autotrader.tools.market_data import MarketDataTool
from autotrader.tools.sentiment import SentimentTool

logger = logging.getLogger(__name__)
console = Console()


class Orchestrator:
    """Manages the full trading lifecycle.

    Loop: Scan → Analyze → Risk Check → Execute → Log
    """

    def __init__(self, config: Config) -> None:
        self.config = config

        # Layer 2: Sensory Tools
        self.market_data = MarketDataTool(config)
        self.sentiment = SentimentTool()
        self.indicators = TechnicalIndicatorTool(
            short_period=config.short_ma_period,
            long_period=config.long_ma_period,
            rsi_period=config.rsi_period,
            rsi_oversold=config.rsi_oversold,
            rsi_overbought=config.rsi_overbought,
        )

        # Layer 3: Strategy (ensemble = ML + technical + sentiment)
        self.ml = MLPredictor()
        self.strategy = EnsembleStrategy(config)

        # Layer 4: Risk Management (fee-aware)
        self.audit = AuditLogger(config.db_path)
        self.risk = RiskManager(config, self.audit)

        # Layer 5: Execution
        self.broker = BrokerTool(config)

        # Memory
        self.memory = MemoryStore()

        self._running = False
        self._cycle_count = 0
        self._snapshots: dict[str, IndicatorSnapshot] = {}

    # ------------------------------------------------------------------ #
    #  Main loop                                                          #
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Start the continuous trading loop."""
        self._running = True
        console.print(
            f"\n[bold green]AI Crypto Trader started[/bold green] | "
            f"Mode: [bold]{self.config.trading_mode.value}[/bold] | "
            f"Pairs: {', '.join(self.config.trading_pairs)} | "
            f"Interval: {self.config.scan_interval_seconds}s | "
            f"Round-trip fee: {self.config.round_trip_fee_pct:.2%}\n"
        )

        try:
            while self._running:
                self._cycle_count += 1
                console.rule(f"[bold blue]Cycle #{self._cycle_count}")
                self._run_cycle()
                if self._running:
                    interval = self.config.scan_interval_seconds
                    logger.info("Sleeping %ds until next cycle...", interval)
                    time.sleep(self.config.scan_interval_seconds)
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down gracefully...[/yellow]")
        finally:
            self.shutdown()

    def run_single_cycle(self) -> list[dict[str, Any]]:
        """Run one scan-analyze-execute cycle and return results (for testing)."""
        self._cycle_count += 1
        return self._run_cycle()

    # ------------------------------------------------------------------ #
    #  Core cycle                                                         #
    # ------------------------------------------------------------------ #
    def _run_cycle(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        # Check kill switch
        if self.risk.is_killed:
            console.print("[bold red]Kill switch active — skipping cycle[/bold red]")
            return results

        for pair in self.config.trading_pairs:
            try:
                result = self._process_pair(pair)
                results.append(result)
            except Exception:
                logger.exception("Error processing %s", pair)
                results.append({"pair": pair, "error": True})

        # Check open positions for stop-loss / take-profit / trailing stop
        self._check_exit_conditions()

        # Bootstrap ML training from candle history on first cycles
        if self._cycle_count <= 3 and not self.ml.is_trained:
            self._bootstrap_ml()

        # Print summary
        self._print_summary(results)
        return results

    def _process_pair(self, pair: str) -> dict[str, Any]:
        """Scan → Analyze → Risk → Execute for a single pair."""
        result: dict[str, Any] = {"pair": pair, "action": "hold", "signal": None}

        # ---- SCAN: fetch market data ----
        console.print(f"  [cyan]Scanning {pair}...[/cyan]")
        candles = self.market_data.get_candles(pair, granularity="ONE_HOUR", limit=100)
        current_price = self.market_data.get_current_price(pair)
        self.memory.store_candles(pair, candles)

        if not candles or current_price <= 0:
            logger.warning("No data for %s — skipping", pair)
            return result

        result["price"] = current_price

        # ---- ANALYZE: compute indicators + sentiment + ML ----
        snapshot = self.indicators.compute(pair, candles)
        if snapshot is None:
            return result
        self._snapshots[pair] = snapshot

        asset = pair.split("-")[0]
        sentiment_result = self.sentiment.analyze(asset)
        sentiment_score = sentiment_result["normalized"]

        # ML prediction
        ml_prediction = self.ml.predict(snapshot)

        # Check long-term memory for bad streaks
        if self.memory.should_avoid_pair(pair):
            self.audit.log_decision(
                pair=pair,
                action="skip",
                reasoning="Long-term memory: consecutive losses — avoiding pair",
            )
            console.print(f"  [yellow]Skipping {pair} — recent loss streak[/yellow]")
            result["action"] = "skip_loss_streak"
            return result

        # ---- STRATEGY: ensemble signal (ML + technical + sentiment) ----
        has_position = self.memory.has_open_position(pair)
        signal = self.strategy.evaluate(
            pair, snapshot, ml_prediction, sentiment_score, has_position
        )
        result["signal"] = {
            "action": signal.action.value,
            "confidence": signal.confidence,
            "reasoning": signal.reasoning,
        }

        self.audit.log_decision(
            pair=pair,
            action=signal.action.value,
            reasoning=signal.reasoning,
            data={
                **snapshot.to_dict(),
                "ml": ml_prediction.to_dict(),
                "sentiment": sentiment_score,
            },
        )

        if not signal.is_actionable:
            console.print(f"  [dim]{pair}: HOLD — {signal.reasoning[:100]}[/dim]")
            return result

        # ---- RISK CHECK (fee-aware) ----
        wallet_usd = self.broker.get_total_balance_usd(
            prices={p: self.market_data.get_current_price(p) for p in self.config.trading_pairs}
        )
        risk_decision = self.risk.evaluate(signal, wallet_usd, current_price, snapshot)

        if not risk_decision.approved:
            reason = risk_decision.reason
            console.print(f"  [red]{pair}: BLOCKED — {reason}[/red]")
            self.audit.log_decision(
                pair=pair,
                action="risk_blocked",
                reasoning=risk_decision.reason,
            )
            result["action"] = "risk_blocked"
            return result

        # ---- EXECUTE ----
        result["action"] = signal.action.value
        if signal.action == SignalAction.BUY:
            self._execute_buy(pair, signal, risk_decision.quantity, current_price, risk_decision)
        elif signal.action == SignalAction.SELL:
            self._execute_sell(pair, signal, current_price)

        return result

    # ------------------------------------------------------------------ #
    #  Execution helpers                                                  #
    # ------------------------------------------------------------------ #
    def _execute_buy(
        self,
        pair: str,
        signal: TradeSignal,
        quantity: float,
        price: float,
        risk_decision: Any,
    ) -> None:
        order = self.broker.place_market_order(pair, "buy", quantity, price)
        if not order.success:
            console.print(f"  [red]ORDER FAILED: {order.message}[/red]")
            return

        # Track in memory (with trailing stop)
        self.memory.open_position(
            Position(
                pair=pair,
                side="buy",
                quantity=quantity,
                entry_price=price,
                stop_loss=risk_decision.stop_loss,
                take_profit=risk_decision.take_profit,
                order_id=order.order_id,
                trailing_stop_pct=risk_decision.trailing_stop_pct,
                entry_fee_usd=order.fee_usd,
            )
        )

        # Record features for ML training
        snapshot = self._snapshots.get(pair)
        if snapshot is not None:
            self.ml.record_entry(pair, snapshot, price)

        # Audit log
        self.audit.log_trade(
            pair=pair,
            side="buy",
            quantity=quantity,
            price=price,
            order_id=order.order_id,
            strategy=signal.strategy,
            confidence=signal.confidence,
            reasoning=signal.reasoning,
            stop_loss=risk_decision.stop_loss,
            take_profit=risk_decision.take_profit,
            fee_usd=order.fee_usd,
        )

        console.print(
            f"  [bold green]BUY {pair}[/bold green] | "
            f"qty={quantity:.6f} @ ${price:,.2f} | "
            f"SL=${risk_decision.stop_loss:,.2f} TP=${risk_decision.take_profit:,.2f} | "
            f"fee=${order.fee_usd:.2f} | confidence={signal.confidence:.2f}"
        )

    def _execute_sell(self, pair: str, signal: TradeSignal, price: float) -> None:
        position = self.memory.get_position(pair)
        if position is None:
            return

        order = self.broker.place_market_order(pair, "sell", position.quantity, price)
        if not order.success:
            console.print(f"  [red]SELL ORDER FAILED: {order.message}[/red]")
            return

        trade_result = self.memory.close_position(pair, price, signal.strategy, signal.reasoning)
        if trade_result:
            # Adjust P&L for fees (entry fee + exit fee)
            total_fees = position.entry_fee_usd + order.fee_usd
            net_pnl = trade_result.pnl - total_fees
            self.audit.update_daily_pnl(net_pnl)
            self.audit.log_trade(
                pair=pair,
                side="sell",
                quantity=position.quantity,
                price=price,
                order_id=order.order_id,
                strategy=signal.strategy,
                confidence=signal.confidence,
                reasoning=signal.reasoning,
                fee_usd=order.fee_usd,
            )

            # Record exit for ML training
            self.ml.record_exit(pair, price)

            pnl_color = "green" if net_pnl >= 0 else "red"
            console.print(
                f"  [bold {pnl_color}]SELL {pair}[/bold {pnl_color}] | "
                f"qty={position.quantity:.6f} @ ${price:,.2f} | "
                f"Gross PnL: ${trade_result.pnl:,.2f} | "
                f"Fees: ${total_fees:.2f} | "
                f"Net PnL: ${net_pnl:,.2f}"
            )

    # ------------------------------------------------------------------ #
    #  Stop-loss / take-profit / trailing stop monitoring                 #
    # ------------------------------------------------------------------ #
    def _check_exit_conditions(self) -> None:
        pairs_to_close: list[tuple[str, str]] = []
        for pair, position in self.memory.open_positions.items():
            current_price = self.market_data.get_current_price(pair)
            if current_price <= 0:
                continue

            # Update trailing stop high-water mark
            position.update_high_water(current_price)
            trailing_stop = position.trailing_stop_price

            # Use the higher of fixed stop-loss or trailing stop
            effective_stop = max(position.stop_loss, trailing_stop)

            if current_price <= effective_stop:
                stop_type = (
                    "trailing_stop" if trailing_stop > position.stop_loss else "stop_loss"
                )
                pairs_to_close.append((pair, stop_type))
                console.print(
                    f"  [bold red]STOP HIT ({stop_type}) for {pair} @ ${current_price:,.2f} "
                    f"(stop=${effective_stop:,.2f})[/bold red]"
                )
            elif current_price >= position.take_profit:
                pairs_to_close.append((pair, "take_profit"))
                console.print(
                    f"  [bold green]TAKE-PROFIT HIT for {pair} @ ${current_price:,.2f} "
                    f"(TP=${position.take_profit:,.2f})[/bold green]"
                )

        for pair, reason in pairs_to_close:
            price = self.market_data.get_current_price(pair)
            signal = TradeSignal(
                pair=pair,
                action=SignalAction.SELL,
                confidence=1.0,
                strategy=reason,
                reasoning=f"Automatic exit: {reason}",
            )
            self._execute_sell(pair, signal, price)

    # ------------------------------------------------------------------ #
    #  ML bootstrap from candle history                                   #
    # ------------------------------------------------------------------ #
    def _bootstrap_ml(self) -> None:
        """Train ML model on historical candle data (look-ahead labels)."""
        for pair in self.config.trading_pairs:
            candles = list(self.memory.recent_candles.get(pair, []))
            if len(candles) < self.indicators.long_period + 20:
                continue

            # Compute indicators at each historical point and label with future returns
            for i in range(self.indicators.long_period + 5, len(candles) - 5):
                window = candles[: i + 1]
                snap = self.indicators.compute(pair, window)
                if snap is None:
                    continue

                # Label: what happened 5 candles later?
                future_price = candles[min(i + 5, len(candles) - 1)]["close"]
                current = candles[i]["close"]
                if current > 0:
                    future_return = (future_price - current) / current
                    self.ml.add_candle_sample(snap.to_feature_vector(), future_return)

        if self.ml.sample_count >= 30:
            trained = self.ml.bootstrap_train()
            if trained:
                console.print(
                    f"  [bold cyan]ML model trained on {self.ml.sample_count} "
                    f"historical samples[/bold cyan]"
                )

    # ------------------------------------------------------------------ #
    #  Display                                                            #
    # ------------------------------------------------------------------ #
    def _print_summary(self, results: list[dict[str, Any]]) -> None:
        table = Table(title=f"Cycle #{self._cycle_count} Summary")
        table.add_column("Pair", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("Action", justify="center")
        table.add_column("Confidence", justify="right")
        table.add_column("Regime", justify="center")
        table.add_column("Reasoning")

        for r in results:
            price_str = f"${r.get('price', 0):,.2f}" if r.get("price") else "N/A"
            sig = r.get("signal", {})
            action = r.get("action", "hold")
            conf = f"{sig.get('confidence', 0):.2f}" if sig else "—"
            reason = sig.get("reasoning", "") if sig else r.get("action", "")

            # Get regime from snapshot
            pair = r["pair"]
            snap = self._snapshots.get(pair)
            regime = snap.regime if snap else "—"

            style = {"buy": "green", "sell": "red", "hold": "dim"}.get(action, "yellow")
            table.add_row(
                pair, price_str, f"[{style}]{action}[/{style}]", conf, regime, reason[:80]
            )

        console.print(table)

        # Wallet summary
        balances = self.broker.get_wallet_balance()
        console.print(f"  Wallet: {balances}")
        console.print(f"  Open positions: {list(self.memory.open_positions.keys()) or 'None'}")
        wr = self.memory.win_rate
        wins, losses = self.memory.win_count, self.memory.loss_count
        console.print(f"  Win rate: {wr:.1%} ({wins}W / {losses}L)")
        console.print(f"  Daily PnL: ${self.audit.get_daily_pnl():,.2f}")
        console.print(f"  Total fees paid: ${self.broker.total_fees_paid:,.2f}")
        ml_status = (
            f"trained ({self.ml.sample_count} samples)"
            if self.ml.is_trained
            else f"warming up ({self.ml.sample_count}/{30} samples)"
        )
        console.print(f"  ML model: {ml_status}\n")

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    def shutdown(self) -> None:
        self._running = False
        self.sentiment.close()
        self.audit.close()
        console.print("[bold yellow]Agent shut down.[/bold yellow]")
