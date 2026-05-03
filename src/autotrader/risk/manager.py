"""Risk Management Guardrail — must approve every trade before execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from autotrader.config import Config
from autotrader.logging.audit import AuditLogger
from autotrader.strategy.signals import SignalAction, TradeSignal

logger = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    """Result of risk evaluation."""

    approved: bool
    quantity: float
    stop_loss: float
    take_profit: float
    reason: str


class RiskManager:
    """Enforces position sizing, stop-loss/take-profit, and the kill switch.

    Every trade signal must pass through ``evaluate()`` before execution.
    """

    def __init__(self, config: Config, audit: AuditLogger) -> None:
        self._config = config
        self._audit = audit
        self._kill_switch_active = False

    # ------------------------------------------------------------------ #
    #  Main evaluation                                                    #
    # ------------------------------------------------------------------ #
    def evaluate(
        self,
        signal: TradeSignal,
        wallet_balance_usd: float,
        current_price: float,
    ) -> RiskDecision:
        """Check the signal against all risk rules and return a decision."""

        # 1. Kill switch check
        if self._kill_switch_active:
            return RiskDecision(
                approved=False,
                quantity=0,
                stop_loss=0,
                take_profit=0,
                reason="Kill switch is active — all trading halted",
            )

        daily_pnl = self._audit.get_daily_pnl()
        loss_limit = wallet_balance_usd * self._config.daily_loss_limit_pct
        if daily_pnl < -loss_limit:
            self._kill_switch_active = True
            logger.critical(
                "KILL SWITCH ACTIVATED | Daily PnL $%.2f exceeds limit -$%.2f",
                daily_pnl,
                loss_limit,
            )
            self._audit.log_decision(
                pair=signal.pair,
                action="kill_switch",
                reasoning=f"Daily loss ${daily_pnl:.2f} exceeded limit -${loss_limit:.2f}",
            )
            return RiskDecision(
                approved=False,
                quantity=0,
                stop_loss=0,
                take_profit=0,
                reason=(
                    f"Kill switch triggered: daily loss ${daily_pnl:.2f} > limit -${loss_limit:.2f}"
                ),
            )

        # 2. Only process actionable signals
        if signal.action == SignalAction.HOLD:
            return RiskDecision(
                approved=False,
                quantity=0,
                stop_loss=0,
                take_profit=0,
                reason="Signal is HOLD — no action required",
            )

        # 3. Position sizing (max % of wallet)
        max_trade_usd = wallet_balance_usd * self._config.max_position_pct
        quantity = max_trade_usd / current_price if current_price > 0 else 0

        if quantity <= 0:
            return RiskDecision(
                approved=False,
                quantity=0,
                stop_loss=0,
                take_profit=0,
                reason="Computed position size is zero or negative",
            )

        # 4. Stop-loss / take-profit
        if signal.action == SignalAction.BUY:
            stop_loss = current_price * (1 - self._config.default_stop_loss_pct)
            take_profit = current_price * (1 + self._config.default_take_profit_pct)
        else:
            stop_loss = current_price * (1 + self._config.default_stop_loss_pct)
            take_profit = current_price * (1 - self._config.default_take_profit_pct)

        # 5. Minimum confidence gate
        min_confidence = 0.50
        if signal.confidence < min_confidence:
            return RiskDecision(
                approved=False,
                quantity=0,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=f"Signal confidence {signal.confidence:.2f} below minimum {min_confidence}",
            )

        logger.info(
            "RISK APPROVED | %s %s | qty=%.6f | SL=$%.2f TP=$%.2f | confidence=%.2f",
            signal.action.value,
            signal.pair,
            quantity,
            stop_loss,
            take_profit,
            signal.confidence,
        )
        return RiskDecision(
            approved=True,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason="Trade approved by risk manager",
        )

    # ------------------------------------------------------------------ #
    #  Kill switch management                                             #
    # ------------------------------------------------------------------ #
    @property
    def is_killed(self) -> bool:
        return self._kill_switch_active

    def reset_kill_switch(self) -> None:
        """Manual reset — for use after reviewing losses."""
        self._kill_switch_active = False
        logger.warning("Kill switch has been manually reset")
