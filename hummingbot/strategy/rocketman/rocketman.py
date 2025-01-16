import asyncio
import logging
from decimal import Decimal
from typing import Dict

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.data_feed.market_data_provider import MarketDataProvider
from hummingbot.strategy_v2.strategy_base import StrategyBase
from hummingbot.strategy.rocketman.rocketman_config import RocketmanConfig
from hummingbot.strategy.rocketman.rocketman_controller import RocketmanController


class RocketmanStrategy(StrategyBase):
    """
    A V2 strategy implementation of the Rocketman trading strategy.
    This strategy uses technical indicators (RSI, Bollinger Bands, EMA) to identify trading opportunities
    and implements a trailing stop mechanism for position management.
    """

    default_config = RocketmanConfig(
        connector_name="",
        trading_pair="",
        candles_config=[],
        trailing_stop_activation_price_delta=Decimal("0.01"),
        trailing_stop_trailing_delta=Decimal("0.005"),
        order_amount=Decimal("0.1"),
    )

    def __init__(
        self,
        config: RocketmanConfig,
        connectors: Dict[str, ConnectorBase],
    ):
        super().__init__(config)
        self._config = config
        self._connectors = connectors
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.INFO)

        # Initialize market data provider and candles
        self._market_data_provider = self._create_market_data_provider()
        for candles_config in self._config.candles_config:
            self._market_data_provider.initialize_candles_feed(candles_config)

        # Initialize controller
        self._controller = RocketmanController(
            config=self._config,
            market_data_provider=self._market_data_provider,
            actions_queue=asyncio.Queue(),
        )

    def _create_market_data_provider(self) -> MarketDataProvider:
        return MarketDataProvider(self._connectors)

    async def start(self):
        """Start the strategy"""
        await super().start()
        self._logger.info("Strategy started.")

    async def stop(self):
        """Stop the strategy"""
        if self._market_data_provider is not None:
            self._market_data_provider.stop()
        await super().stop()
        self._logger.info("Strategy stopped.")

    @property
    def active_executors(self):
        """Get all active position executors"""
        return self._controller.get_all_executors()

    async def on_start(self):
        """Called when strategy starts"""
        self._logger.info(
            f"Strategy starting with config: connector={self._config.connector_name}, "
            f"trading_pair={self._config.trading_pair}"
        )

    async def on_stop(self):
        """Called when strategy stops"""
        if self._market_data_provider is not None:
            self._market_data_provider.stop()

    async def on_tick(self):
        """
        Main strategy logic executed on each tick:
        - Update controller's processed data (includes current price and signal)
        - Process any pending actions from controller
        - Log status of active executors
        """
        try:
            await self._controller.update_processed_data()

            # Log current signal and price
            if "signal" in self._controller.processed_data:
                self._logger.info(
                    f"Current signal: {self._controller.processed_data['signal']}"
                )
            if "current_price" in self._controller.processed_data:
                self._logger.info(
                    f"Current price: {self._controller.processed_data['current_price']}"
                )

            # Process any pending actions from controller
            while not self._controller.actions_queue.empty():
                action = await self._controller.actions_queue.get()
                await self._controller.process_action(action)

            # Log status of active executors
            active_executors = self._controller.get_all_executors()
            if not active_executors:
                self._logger.info("No active executors")
            else:
                for executor in active_executors:
                    self._logger.info(f"Active executor: {executor}")

        except Exception as e:
            self._logger.error(f"Error in on_tick: {str(e)}", exc_info=True)

    @property
    def connectors(self) -> Dict[str, ConnectorBase]:
        """Get the strategy's connectors"""
        return self._connectors

    @property
    def controller(self) -> RocketmanController:
        """Get the strategy's controller"""
        return self._controller
