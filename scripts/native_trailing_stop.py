#!/usr/bin/env python

import asyncio
import logging
from decimal import Decimal
from typing import Dict, List, Optional, Set
import pandas as pd
import time

from pydantic import Field

from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.strategy_v2.executors.position_executor.position_executor import (
    PositionExecutor,
)
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.executors.position_executor.data_types import (
    TripleBarrierConfig,
)
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.data_feed.market_data_provider import MarketDataProvider
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction


class TrailingStopControllerConfig(DirectionalTradingControllerConfigBase):
    controller_name: str = "trailing_stop"
    candles_config: List[CandlesConfig] = []
    trailing_stop_activation_price_delta: Decimal = Field(
        default=Decimal("0.01"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the trailing stop activation price delta (e.g. 0.01 for 1%): ",
            prompt_on_new=True,
        ),
    )
    trailing_stop_trailing_delta: Decimal = Field(
        default=Decimal("0.005"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the trailing stop trailing delta (e.g. 0.005 for 0.5%): ",
            prompt_on_new=True,
        ),
    )
    order_amount: Decimal = Field(
        default=Decimal("0.1"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the order amount: ", prompt_on_new=True
        ),
    )


class TrailingStopController(DirectionalTradingControllerBase):
    def __init__(
        self,
        config: TrailingStopControllerConfig,
        market_data_provider,
        actions_queue,
    ):
        super().__init__(config, market_data_provider, actions_queue)
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.INFO)
        self._executors = []

    async def update_processed_data(self):
        try:
            # Get the current price from the connector
            connector = self.market_data_provider.connectors[self.config.connector_name]
            current_price = await connector.get_quote_price(
                self.config.trading_pair,
                is_buy=True,  # We'll use the buy price as mid price
                amount=Decimal("1"),  # Get price for 1 unit
            )

            # Get candles data if available
            candles_df = self.market_data_provider.get_candles_df(
                connector=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                interval=self.config.candles_config[0].interval
                if self.config.candles_config
                else "1m",
            )

            if candles_df is not None and not candles_df.empty:
                # Calculate technical indicators
                rsi = self.calculate_rsi(candles_df["close"], period=14)
                bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(
                    candles_df["close"], period=20
                )
                ema = self.calculate_ema(candles_df["close"], period=20)

                # Store the latest values
                self.processed_data = {
                    "current_price": current_price,
                    "rsi": rsi.iloc[-1] if not rsi.empty else None,
                    "bb_lower": bb_lower.iloc[-1] if not bb_lower.empty else None,
                    "bb_upper": bb_upper.iloc[-1] if not bb_upper.empty else None,
                    "ema": ema.iloc[-1] if not ema.empty else None,
                }

                # Generate signal based on conditions
                active_executors = self.get_all_executors()
                if not active_executors:
                    if (
                        rsi.iloc[-1] < 30
                        and current_price < bb_lower.iloc[-1]
                        and current_price < ema.iloc[-1]
                    ):
                        self.processed_data["signal"] = 1  # Buy signal
                    else:
                        self.processed_data["signal"] = 0
                else:
                    self.processed_data["signal"] = (
                        0  # No signal while position is active
                    )

            else:
                # If no candles data available, just store the current price
                self.processed_data = {"current_price": current_price, "signal": 0}

            self._logger.info(
                f"Processed data updated - Price: {current_price}, Signal: {self.processed_data['signal']}"
            )

        except Exception as e:
            self._logger.error(f"Error updating processed data: {str(e)}")
            self.processed_data = {"current_price": None, "signal": 0}

    def get_all_executors(self) -> List[PositionExecutor]:
        return self._executors

    def filter_executors(self, condition) -> List[PositionExecutor]:
        return [executor for executor in self._executors if condition(executor)]

    async def create_position_executor(self, executor_config):
        executor = await super().create_position_executor(executor_config)
        self._executors.append(executor)
        return executor

    @staticmethod
    def calculate_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_bollinger_bands(series, period=20, std_dev=2):
        rolling_mean = series.rolling(window=period).mean()
        rolling_std = series.rolling(window=period).std()
        upper_band = rolling_mean + (rolling_std * std_dev)
        lower_band = rolling_mean - (rolling_std * std_dev)
        return upper_band, rolling_mean, lower_band

    @staticmethod
    def calculate_ema(series, period=20):
        return series.ewm(span=period, adjust=False).mean()


class NativeTrailingStop(ScriptStrategyBase):
    markets = {"jupiter_solana_mainnet-beta": {"ai16z-USDC"}}

    def __init__(self, connectors: Dict[str, ConnectorBase]):
        super().__init__(connectors)
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.INFO)
        self.trading_pair = "ai16z-USDC"
        self.connector_name = "jupiter_solana_mainnet-beta"

        # Initialize controller config with candles
        controller_config = TrailingStopControllerConfig(
            connector_name=self.connector_name,
            trading_pair=self.trading_pair,
            candles_config=[
                CandlesConfig(
                    connector=self.connector_name,
                    trading_pair=self.trading_pair,
                    interval="10s",  # 10-second candles
                    max_records=1000,  # Keep last 1000 candles
                )
            ],
            trailing_stop_activation_price_delta=Decimal(
                "0.01"
            ),  # 1% profit activation
            trailing_stop_trailing_delta=Decimal("0.005"),  # 0.5% trailing distance
            order_amount=Decimal("0.1"),
        )

        # Create market data provider and initialize candles
        self.market_data_provider = self.create_market_data_provider()
        # Initialize each candles feed separately
        for candles_config in controller_config.candles_config:
            self.market_data_provider.initialize_candles_feed(candles_config)

        # Initialize controller
        self.controller = TrailingStopController(
            config=controller_config,
            market_data_provider=self.market_data_provider,
            actions_queue=asyncio.Queue(),
        )

    def create_market_data_provider(self):
        market_data_provider = MarketDataProvider(
            self.connectors,
        )
        return market_data_provider

    async def on_stop(self):
        """Stop candles feed when strategy stops"""
        if self.market_data_provider is not None:
            self.market_data_provider.stop()

    async def on_tick(self):
        """
        - Update controller's processed data (includes current price and signal)
        - Process any pending actions from controller
        - Log status of active executors
        """
        try:
            await self.controller.update_processed_data()

            # Log current signal and price
            if "signal" in self.controller.processed_data:
                self._logger.info(
                    f"Current signal: {self.controller.processed_data['signal']}"
                )
            if "current_price" in self.controller.processed_data:
                self._logger.info(
                    f"Current price: {self.controller.processed_data['current_price']}"
                )

            # Process any pending actions from controller
            while not self.controller.actions_queue.empty():
                action = await self.controller.actions_queue.get()
                if isinstance(action, CreateExecutorAction):
                    await self.controller.create_position_executor(
                        action.executor_config
                    )

            # Log status of active executors
            active_executors = self.controller.get_all_executors()
            if not active_executors:
                self._logger.info("No active executors")
            else:
                for executor in active_executors:
                    self._logger.info(
                        f"Executor {executor.id} status: {executor.status}"
                    )

        except Exception as e:
            self._logger.error(f"Error in on_tick: {str(e)}")

    def format_status(self) -> str:
        if not self.ready:
            return "Market connectors are not ready..."
        lines = []
        lines.extend(["\n# Market Status"])

        # Add current price and signal
        if self.controller and self.controller.processed_data:
            current_price = self.controller.processed_data.get("current_price")
            signal = self.controller.processed_data.get("signal")
            lines.extend(
                [
                    f"Current price: {current_price}",
                    f"Signal: {signal} (-1: sell, 0: no action, 1: buy)",
                ]
            )

            # Add technical indicators if available
            rsi = self.controller.processed_data.get("rsi")
            bb_lower = self.controller.processed_data.get("bb_lower")
            bb_upper = self.controller.processed_data.get("bb_upper")
            ema = self.controller.processed_data.get("ema")

            if all(v is not None for v in [rsi, bb_lower, bb_upper, ema]):
                lines.extend(
                    [
                        f"RSI: {rsi:.2f}",
                        f"Bollinger Bands: {bb_lower:.2f} - {bb_upper:.2f}",
                        f"EMA: {ema:.2f}",
                    ]
                )

        # Add active executors status
        lines.extend(["\n# Active Executors"])
        active_executors = self.controller.get_all_executors()
        if not active_executors:
            lines.extend(["No active executors"])
        else:
            for executor in active_executors:
                lines.extend(
                    [
                        f"Executor {executor.id}:",
                        f"  Status: {executor.status}",
                        f"  Position: {executor.trading_pair}",
                    ]
                )
        return "\n".join(lines)
