#!/usr/bin/env python

from typing import Dict, Set

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.rocketman_v2.rocketman import RocketmanStrategy


class RocketmanLiveScript(ScriptStrategyBase):
    """Live trading script for Rocketman V2 Strategy using Jupiter."""

    markets = {"jupiter_solana_mainnet-beta": {"AI16Z-USDC"}}

    def __init__(self, markets: Dict[str, Set[str]]):
        super().__init__(markets)
        self.strategy = RocketmanStrategy(self.config)

    def start(self, clock, timestamp: float):
        if self.strategy:
            self.strategy.start(clock, timestamp)

    def on_stop(self):
        if self.strategy:
            self.strategy.stop()

    def format_status(self) -> str:
        return (
            self.strategy.format_status()
            if self.strategy
            else "Strategy not initialized."
        )
