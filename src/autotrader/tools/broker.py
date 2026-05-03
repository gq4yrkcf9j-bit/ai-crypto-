"""Broker Tool — executes trades via Coinbase Advanced Trade API."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from coinbase.rest import RESTClient

from autotrader.config import Config, TradingMode

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """Result of an order placement."""

    success: bool
    order_id: str
    pair: str
    side: str
    quantity: float
    price: float
    message: str = ""


class BrokerTool:
    """Places and manages orders on Coinbase (or simulates them in paper mode)."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: RESTClient | None = None
        if config.has_credentials and config.trading_mode == TradingMode.LIVE:
            self._client = RESTClient(
                api_key=config.coinbase_api_key,
                api_secret=config.coinbase_api_secret,
            )
        self._paper_balance: dict[str, float] = {"USD": 10_000.0}
        self._paper_positions: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #
    def place_market_order(
        self,
        pair: str,
        side: str,
        quantity: float,
        current_price: float,
    ) -> OrderResult:
        if self._config.trading_mode == TradingMode.LIVE and self._client is not None:
            return self._live_market_order(pair, side, quantity)
        return self._paper_market_order(pair, side, quantity, current_price)

    def place_limit_order(
        self,
        pair: str,
        side: str,
        quantity: float,
        limit_price: float,
    ) -> OrderResult:
        if self._config.trading_mode == TradingMode.LIVE and self._client is not None:
            return self._live_limit_order(pair, side, quantity, limit_price)
        return self._paper_market_order(pair, side, quantity, limit_price)

    def get_wallet_balance(self) -> dict[str, float]:
        if self._config.trading_mode == TradingMode.LIVE and self._client is not None:
            return self._live_balance()
        return dict(self._paper_balance)

    def get_total_balance_usd(self, prices: dict[str, float] | None = None) -> float:
        """Return total portfolio value in USD."""
        balances = self.get_wallet_balance()
        total = balances.get("USD", 0.0)
        prices = prices or {}
        for asset, qty in balances.items():
            if asset == "USD":
                continue
            pair = f"{asset}-USD"
            price = prices.get(pair, 0.0)
            total += qty * price
        return total

    # ------------------------------------------------------------------ #
    #  Live orders (Coinbase)                                             #
    # ------------------------------------------------------------------ #
    def _live_market_order(self, pair: str, side: str, quantity: float) -> OrderResult:
        assert self._client is not None
        try:
            client_oid = str(uuid.uuid4())
            if side == "buy":
                resp = self._client.market_order_buy(
                    client_order_id=client_oid,
                    product_id=pair,
                    base_size=str(quantity),
                )
            else:
                resp = self._client.market_order_sell(
                    client_order_id=client_oid,
                    product_id=pair,
                    base_size=str(quantity),
                )

            order_id = resp.get("order_id", client_oid) if isinstance(resp, dict) else client_oid
            success = True
            message = "Order placed successfully"
            logger.info(
                "LIVE ORDER | %s %s %.6f %s | order_id=%s", side, pair, quantity, pair, order_id
            )
            return OrderResult(
                success=success,
                order_id=order_id,
                pair=pair,
                side=side,
                quantity=quantity,
                price=0.0,  # filled price determined by market
                message=message,
            )
        except Exception as exc:
            logger.exception("Failed to place live order for %s", pair)
            return OrderResult(
                success=False,
                order_id="",
                pair=pair,
                side=side,
                quantity=quantity,
                price=0.0,
                message=str(exc),
            )

    def _live_limit_order(
        self, pair: str, side: str, quantity: float, limit_price: float
    ) -> OrderResult:
        assert self._client is not None
        try:
            client_oid = str(uuid.uuid4())
            if side == "buy":
                resp = self._client.limit_order_gtc_buy(
                    client_order_id=client_oid,
                    product_id=pair,
                    base_size=str(quantity),
                    limit_price=str(limit_price),
                )
            else:
                resp = self._client.limit_order_gtc_sell(
                    client_order_id=client_oid,
                    product_id=pair,
                    base_size=str(quantity),
                    limit_price=str(limit_price),
                )

            order_id = resp.get("order_id", client_oid) if isinstance(resp, dict) else client_oid
            logger.info(
                "LIVE LIMIT ORDER | %s %s %.6f @ $%.2f | order_id=%s",
                side,
                pair,
                quantity,
                limit_price,
                order_id,
            )
            return OrderResult(
                success=True,
                order_id=order_id,
                pair=pair,
                side=side,
                quantity=quantity,
                price=limit_price,
                message="Limit order placed",
            )
        except Exception as exc:
            logger.exception("Failed to place live limit order for %s", pair)
            return OrderResult(
                success=False,
                order_id="",
                pair=pair,
                side=side,
                quantity=quantity,
                price=limit_price,
                message=str(exc),
            )

    def _live_balance(self) -> dict[str, float]:
        assert self._client is not None
        try:
            accounts = self._client.get_accounts()
            balances: dict[str, float] = {}
            account_list = accounts.get("accounts", []) if isinstance(accounts, dict) else []
            for acct in account_list:
                if isinstance(acct, dict):
                    currency = acct.get("currency", "")
                    available = float(acct.get("available_balance", {}).get("value", 0))
                    if available > 0:
                        balances[currency] = available
            return balances
        except Exception:
            logger.exception("Failed to fetch live balances")
            return {}

    # ------------------------------------------------------------------ #
    #  Paper trading simulation                                           #
    # ------------------------------------------------------------------ #
    def _paper_market_order(
        self, pair: str, side: str, quantity: float, price: float
    ) -> OrderResult:
        base, quote = pair.split("-")
        cost = quantity * price
        order_id = f"paper-{uuid.uuid4().hex[:12]}"

        if side == "buy":
            if self._paper_balance.get(quote, 0) < cost:
                return OrderResult(
                    success=False,
                    order_id=order_id,
                    pair=pair,
                    side=side,
                    quantity=quantity,
                    price=price,
                    message=f"Insufficient {quote} balance: need ${cost:.2f}",
                )
            self._paper_balance[quote] = self._paper_balance.get(quote, 0) - cost
            self._paper_balance[base] = self._paper_balance.get(base, 0) + quantity
        else:
            if self._paper_balance.get(base, 0) < quantity:
                return OrderResult(
                    success=False,
                    order_id=order_id,
                    pair=pair,
                    side=side,
                    quantity=quantity,
                    price=price,
                    message=f"Insufficient {base} balance: have {self._paper_balance.get(base, 0)}",
                )
            self._paper_balance[base] = self._paper_balance.get(base, 0) - quantity
            self._paper_balance[quote] = self._paper_balance.get(quote, 0) + cost

        logger.info(
            "PAPER ORDER | %s %s %.6f @ $%.2f (cost=$%.2f) | balances=%s",
            side,
            pair,
            quantity,
            price,
            cost,
            self._paper_balance,
        )
        return OrderResult(
            success=True,
            order_id=order_id,
            pair=pair,
            side=side,
            quantity=quantity,
            price=price,
            message=f"Paper {side} filled at ${price:.2f}",
        )
