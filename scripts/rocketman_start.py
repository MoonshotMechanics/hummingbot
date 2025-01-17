#!/usr/bin/env python

import logging
from typing import Dict, Set
from datetime import datetime, timedelta
from decimal import Decimal

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.rocketman_v2.rocketman import RocketmanStrategy
from hummingbot.strategy_v2.rocketman_v2.configs.rocketman_config import RocketmanConfig
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.core.data_type.common import OrderType, PositionMode
from hummingbot.core.clock import Clock


class RocketmanScript(ScriptStrategyBase):
    markets = {"jupiter_solana_mainnet-beta": {"AI16Z-USDC"}}

    def __init__(self, markets: Dict[str, Set[str]]):
        super().__init__(markets)
        self.strategy = None
        print("\n=== Rocketman V2 Strategy ===")
        print("\nSelect trading mode:")
        print("1. Live Trading  - Trade AI16Z-USDC on Jupiter in real-time")
        print("2. Backtesting   - Test strategy with historical Birdeye data")
        print("\nNote: Backtesting mode uses 3 days of historical candle data.")

        mode = input("\nEnter your choice (1 or 2): ")

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

        # Initialize strategy config
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

        if mode == "1":
            self.strategy = RocketmanStrategy(config)
            print("Live strategy initialized.")
        else:
            from scripts.rocketman_backtest import RocketmanBacktestScript

            self.strategy = (
                RocketmanBacktestScript()
            )  # No markets needed for backtesting
            print("Backtesting strategy initialized.")

    async def start(self, clock: Clock, timestamp: float):
        if self.strategy:
            await self.strategy.start(clock, timestamp)

    def on_stop(self):
        if self.strategy:
            self.strategy.stop()

    def format_status(self) -> str:
        return (
            self.strategy.format_status()
            if self.strategy
            else "Strategy not initialized."
        )
