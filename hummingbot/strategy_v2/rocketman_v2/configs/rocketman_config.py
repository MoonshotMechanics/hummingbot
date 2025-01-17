from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerConfigBase,
)


@dataclass
class RocketmanConfig(DirectionalTradingControllerConfigBase):
    """
    Configuration class for the Rocketman strategy.
    Focused on trailing stop and take profit functionality using Jupiter connector.
    """

    # Trading parameters
    connector_name: str  # Jupiter connector name
    trading_pair: str  # Trading pair to trade
    order_amount: Decimal  # Amount to trade in quote currency
    leverage: int = 1  # Default leverage is 1 (spot trading)

    # Take profit parameters
    take_profit_percentage: Decimal  # Take profit target as percentage

    # Trailing stop parameters
    trailing_stop_activation_price_delta: (
        Decimal  # Price change needed to activate trailing stop
    )
    trailing_stop_trailing_delta: Decimal  # How far to trail the price

    # Candles configuration for backtesting
    candles_config: Optional[CandlesConfig] = None

    def __post_init__(self):
        """Validate configuration parameters"""
        super().__post_init__()

        # Validate trading parameters
        if self.order_amount <= Decimal("0"):
            raise ValueError("order_amount must be positive")
        if self.leverage <= 0:
            raise ValueError("leverage must be positive")

        # Validate take profit parameters
        if self.take_profit_percentage <= Decimal("0"):
            raise ValueError("take_profit_percentage must be positive")

        # Validate trailing stop parameters
        if self.trailing_stop_activation_price_delta <= Decimal("0"):
            raise ValueError("trailing_stop_activation_price_delta must be positive")
        if self.trailing_stop_trailing_delta <= Decimal("0"):
            raise ValueError("trailing_stop_trailing_delta must be positive")

    @property
    def controller_type(self) -> str:
        return "rocketman_v2"

    @property
    def controller_name(self) -> str:
        return "rocketman"

    @property
    def total_amount_quote(self) -> Decimal:
        """Total amount to trade in quote currency"""
        return self.order_amount
