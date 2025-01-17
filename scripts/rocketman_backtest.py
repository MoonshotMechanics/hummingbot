#!/usr/bin/env python

import asyncio
from decimal import Decimal
from typing import Dict, Set
from datetime import datetime, timedelta

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.rocketman_v2.backtesting.backtesting_executor import (
    BacktestingExecutor,
)
from hummingbot.strategy_v2.rocketman_v2.configs.rocketman_config import RocketmanConfig
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.core.data_type.common import OrderType, PositionMode, TradeType
from hummingbot.core.clock import Clock


class RocketmanBacktestScript(ScriptStrategyBase):
    """Backtesting script for Rocketman V2 Strategy using historical Birdeye data."""

    # Define empty markets to avoid connector initialization
    markets = {}

    def __init__(self, markets: Dict[str, Set[str]] = None):
        # Pass empty dict to avoid connector initialization
        super().__init__({})

        # Disable unnecessary services
        self._ready = True  # Mark strategy as ready immediately
        self._all_markets_ready = True  # Skip market readiness check
        self.disable_time_synchronizer = True  # Disable time sync
        self.disable_rate_oracle = True  # Disable rate oracle

        # Configure candles feed for last 3 days of 5m candles
        end_time = datetime.now()
        start_time = end_time - timedelta(days=3)
        candles_config = CandlesConfig.construct(
            connector="birdeye",
            trading_pair="AI16Z-USDC",
            interval="5m",
            start_time=start_time,
            end_time=end_time,
        )

        # Initialize strategy config using model.construct()
        config = RocketmanConfig.construct(
            connector_name="jupiter_solana_mainnet-beta",
            trading_pair="AI16Z-USDC",
            order_amount=Decimal("10"),  # Trade with 10 USDC
            take_profit_percentage=Decimal("2.0"),  # 2% take profit
            trailing_stop_activation_price_delta=Decimal(
                "1.0"
            ),  # Activate at 1% price increase
            trailing_stop_trailing_delta=Decimal("0.5"),  # Trail by 0.5%
            leverage=1,  # Spot trading
            position_mode=PositionMode.ONEWAY,  # Single position mode for spot
            take_profit_order_type=OrderType.LIMIT,  # Use limit orders for take profit
            candles_config=candles_config,  # Historical data configuration
        )

        self.executor = BacktestingExecutor(config=config)
        self.backtest_running = False
        self.backtest_complete = False
        self._task = None

    def start(self, clock: Clock, timestamp: float):
        """Start the backtesting strategy."""
        self.backtest_running = True
        print("\nStarting backtest...")
        # Create task for running backtest
        self._task = asyncio.create_task(self._run_backtest())

    def tick(self, timestamp: float):
        """Check backtest status during tick."""
        if self._task and self._task.done():
            try:
                self._task.result()  # This will raise any exceptions that occurred
            except Exception as e:
                print(f"\nBacktest failed with error: {str(e)}")
            finally:
                self._task = None

    async def _run_backtest(self):
        """Internal method to run the backtest."""
        if not self.backtest_complete:
            try:
                # First fetch candles
                candles = await self.executor.utils.load_candles(
                    token_address="HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC",  # AI16Z token address
                    start_time=datetime.now() - timedelta(days=3),
                    end_time=datetime.now(),
                    interval="5m",
                )

                # Log candles to data directory
                import os
                import json

                def decimal_default(obj):
                    if isinstance(obj, Decimal):
                        return str(obj)
                    raise TypeError

                os.makedirs("data", exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"data/birdeye_candles_{timestamp}.json"
                with open(filename, "w") as f:
                    json.dump(candles, f, indent=2, default=decimal_default)
                print(f"\nCandles saved to {filename}")

                # Run backtest with the fetched candles
                results = await self.executor.run_backtest(
                    token_address="HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC",  # AI16Z token address
                    start_time=datetime.now() - timedelta(days=3),
                    end_time=datetime.now(),
                    trade_type=TradeType.BUY,  # Start with a buy position
                    interval="5m",
                )
                print("\nBacktest Results:")
                print(self.executor.format_backtest_results(results))
                self.backtest_complete = True
            except Exception as e:
                print(f"\nError running backtest: {str(e)}")
                raise
            finally:
                self.backtest_running = False

    def on_stop(self):
        """Handle strategy stop."""
        self.backtest_running = False
        if self._task:
            self._task.cancel()

    def format_status(self) -> str:
        """Return the current status of the backtest."""
        if self.backtest_running:
            return "Backtest in progress..."
        elif self.backtest_complete:
            return "Backtest complete."
        return "Backtest not running."
