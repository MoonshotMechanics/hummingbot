from decimal import Decimal
from typing import List

from pydantic import Field

from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerConfigBase,
)
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig


class RocketmanConfig(DirectionalTradingControllerConfigBase):
    controller_name: str = "rocketman"
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
