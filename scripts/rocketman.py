#!/usr/bin/env python

import logging
from decimal import Decimal
from typing import Dict

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import PositionMode
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.rocketman.rocketman import RocketmanStrategy
from hummingbot.strategy_v2.rocketman.rocketman_config import RocketmanConfig
from hummingbot.strategy_v2.executors.position_executor.data_types import TrailingStop


class RocketmanScript(ScriptStrategyBase):
    markets = {"jupiter_solana_mainnet-beta": {"ai16z-USDC"}}

    def __init__(self, connectors: Dict[str, ConnectorBase]):
        super().__init__(connectors)
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.INFO)

        # Market address for AI16Z/USDC pair on Raydium
        ai16z_usdc_market = "HbqujJENLP5cnH662jiaKvnbcVR9zz2HWPKRJob1m2s4"

        # Create strategy config with Birdeye candles
        candles_config = CandlesConfig(
            connector="birdeye",
            trading_pair=ai16z_usdc_market,  # Use market address for price data
            interval="1m",  # Use 1-minute candles
            max_records=1000,
        )

        # Create strategy config
        self.config = RocketmanConfig(
            connector_name="jupiter_solana_mainnet-beta",
            trading_pair="ai16z-USDC",  # Keep original trading pair for Jupiter
            candles_config=[candles_config],
            leverage=1,
            position_mode=PositionMode.ONEWAY,
            order_amount=Decimal("0.1"),
            trailing_stop=TrailingStop(
                activation_price=Decimal("0.01"), trailing_delta=Decimal("0.005")
            ),
            stop_loss=Decimal("0.02"),
            take_profit=Decimal("0.01"),
            time_limit=3600,  # 1 hour
        )

        # Initialize strategy
        RocketmanStrategy.init_markets(self.config)
        self.strategy = RocketmanStrategy(
            connectors=self.connectors, config=self.config
        )

    def on_stop(self):
        if self.strategy is not None:
            self.strategy.stop()

    def format_status(self) -> str:
        return (
            self.strategy.format_status()
            if self.strategy is not None
            else "Strategy not initialized."
        )
