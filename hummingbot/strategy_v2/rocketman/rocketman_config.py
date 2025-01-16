import os
from decimal import Decimal
from typing import Dict, List, Optional, Set

from pydantic import Field, validator

from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.core.data_type.common import OrderType, PositionMode
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy.strategy_v2_base import StrategyV2ConfigBase
from hummingbot.strategy_v2.executors.position_executor.data_types import TrailingStop


class RocketmanConfig(StrategyV2ConfigBase):
    script_file_name: str = Field(default_factory=lambda: os.path.basename(__file__))
    markets: Dict[str, Set[str]] = {}
    candles_config: List[CandlesConfig] = []
    controllers_config: List[str] = []

    # Market configuration
    connector_name: str = Field(
        default="jupiter_solana_mainnet-beta",
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the connector name (e.g., jupiter_solana_mainnet-beta):",
            prompt_on_new=True,
        ),
    )
    trading_pair: str = Field(
        default="ai16z-USDC",
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the trading pair (e.g., ai16z-USDC):",
            prompt_on_new=True,
        ),
    )

    # Trading parameters
    leverage: int = Field(
        default=1,
        gt=0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the leverage to use (e.g., 1 for spot, 10 for 10x leverage):",
            prompt_on_new=True,
        ),
    )
    position_mode: PositionMode = Field(
        default=PositionMode.ONEWAY,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the position mode (ONEWAY or HEDGE):",
            prompt_on_new=True,
        ),
    )
    order_amount: Decimal = Field(
        default=Decimal("0.1"),
        gt=0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the order amount:",
            prompt_on_new=True,
        ),
    )
    stop_loss: Decimal = Field(
        default=Decimal("0.02"),
        gt=0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the stop loss percentage (e.g., 0.02 for 2%):",
            prompt_on_new=True,
        ),
    )
    take_profit: Decimal = Field(
        default=Decimal("0.01"),
        gt=0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the take profit percentage (e.g., 0.01 for 1%):",
            prompt_on_new=True,
        ),
    )
    time_limit: int = Field(
        default=3600,
        gt=0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the time limit in seconds (e.g., 3600 for 1 hour):",
            prompt_on_new=True,
        ),
    )
    trailing_stop: Optional[TrailingStop] = Field(
        default="0.015,0.003",
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the trailing stop as activation_price,trailing_delta (e.g., 0.015,0.003): ",
            prompt_on_new=True,
        ),
    )

    @validator("position_mode", pre=True)
    def validate_position_mode(cls, v: str) -> PositionMode:
        if isinstance(v, PositionMode):
            return v
        if v.upper() in PositionMode.__members__:
            return PositionMode[v.upper()]
        raise ValueError(
            f"Invalid position mode: {v}. Valid options are: {', '.join(PositionMode.__members__)}"
        )

    @validator("markets", pre=True)
    def validate_markets(cls, v: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
        if not v:
            return {}
        return v

    @validator("candles_config", pre=True)
    def validate_candles_config(cls, v: List[CandlesConfig]) -> List[CandlesConfig]:
        if not v:
            return []
        return v

    @validator("controllers_config", pre=True)
    def validate_controllers_config(cls, v: List[str]) -> List[str]:
        if not v:
            return []
        return v

    @validator("trailing_stop", pre=True, always=True)
    def parse_trailing_stop(cls, v):
        if isinstance(v, str):
            if v == "":
                return None
            activation_price, trailing_delta = v.split(",")
            return TrailingStop(
                activation_price=Decimal(activation_price),
                trailing_delta=Decimal(trailing_delta),
            )
        return v
