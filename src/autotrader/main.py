"""Entry point for the AI Crypto Trader."""

from __future__ import annotations

import argparse
import logging
import sys

from rich.console import Console
from rich.panel import Panel

from autotrader.config import Config, TradingMode
from autotrader.orchestrator import Orchestrator

console = Console()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def print_banner(config: Config) -> None:
    mode_color = "red" if config.trading_mode == TradingMode.LIVE else "yellow"
    creds = "Connected" if config.has_credentials else "Not configured (paper only)"

    banner = (
        "[bold cyan]AI Crypto Trader v0.1.0[/bold cyan]\n"
        f"Mode:        [{mode_color}]{config.trading_mode.value.upper()}[/{mode_color}]\n"
        f"Credentials: {creds}\n"
        f"Pairs:       {', '.join(config.trading_pairs)}\n"
        f"Interval:    {config.scan_interval_seconds}s\n"
        f"Risk limit:  {config.max_position_pct:.0%} per trade, "
        f"{config.daily_loss_limit_pct:.0%} daily loss kill-switch\n"
        f"Stop-Loss:   {config.default_stop_loss_pct:.0%} | "
        f"Take-Profit: {config.default_take_profit_pct:.0%}"
    )
    console.print(Panel(banner, title="Configuration", border_style="blue"))


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Crypto Trader")
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default=None,
        help="Trading mode (default: from env or 'paper')",
    )
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=None,
        help="Trading pairs (e.g. BTC-USD ETH-USD)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Scan interval in seconds",
    )
    parser.add_argument(
        "--single-cycle",
        action="store_true",
        help="Run a single scan cycle and exit (useful for testing)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    args = parser.parse_args()

    # Load config from environment / .env file
    config = Config()

    # CLI overrides
    if args.mode:
        config.trading_mode = TradingMode(args.mode)
    if args.pairs:
        config.trading_pairs = args.pairs
    if args.interval:
        config.scan_interval_seconds = args.interval
    if args.log_level:
        config.log_level = args.log_level

    # Safety check for live mode
    if config.trading_mode == TradingMode.LIVE and not config.has_credentials:
        console.print(
            "[bold red]ERROR: Live mode requires COINBASE_API_KEY and COINBASE_API_SECRET "
            "environment variables.[/bold red]"
        )
        sys.exit(1)

    setup_logging(config.log_level)
    print_banner(config)

    # Build and run
    agent = Orchestrator(config)

    if args.single_cycle:
        console.print("[bold]Running single cycle...[/bold]\n")
        agent.run_single_cycle()
        agent.shutdown()
    else:
        agent.run()


if __name__ == "__main__":
    main()
