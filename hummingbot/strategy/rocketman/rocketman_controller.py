import logging
from decimal import Decimal
from typing import List, Optional

import pandas as pd

from hummingbot.strategy.rocketman.rocketman_config import RocketmanConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import DirectionalTradingControllerBase
from hummingbot.strategy_v2.executors.position_executor.position_executor import PositionExecutor


class RocketmanController(DirectionalTradingControllerBase):
    def __init__(
        self,
        config: RocketmanConfig,
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
                is_buy=True,
                amount=Decimal("1"),
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
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_bollinger_bands(
        series: pd.Series, period: int = 20, std_dev: int = 2
    ):
        rolling_mean = series.rolling(window=period).mean()
        rolling_std = series.rolling(window=period).std()
        upper_band = rolling_mean + (rolling_std * std_dev)
        lower_band = rolling_mean - (rolling_std * std_dev)
        return upper_band, rolling_mean, lower_band

    @staticmethod
    def calculate_ema(series: pd.Series, period: int = 20) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()
