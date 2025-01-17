import logging
from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.core.data_type.common import OrderType, PositionAction, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
)

from hummingbot.strategy_v2.rocketman_v2.configs.rocketman_config import RocketmanConfig

logger = logging.getLogger(__name__)


class RocketmanStrategy(DirectionalTradingControllerBase):
    """
    A simplified version of the Rocketman strategy focused on trailing stop and take profit functionality.
    Uses Jupiter connector for trading.
    """

    def __init__(self, config: RocketmanConfig):
        super().__init__(config)
        self._config: RocketmanConfig = config
        self._active_positions: Dict[str, Dict] = {}

    @property
    def config(self) -> RocketmanConfig:
        return self._config

    def create_order_candidate(
        self,
        timestamp: float,
        trade_type: TradeType,
        entry_price: Decimal,
    ) -> OrderCandidate:
        """Create order candidate for entry"""
        return OrderCandidate(
            trading_pair=self.config.trading_pair,
            is_maker=False,
            order_type=OrderType.MARKET,
            order_side=trade_type,
            amount=self.config.order_amount,
            price=entry_price,
        )

    def early_stop_condition(self, timestamp: float) -> bool:
        """No early stop conditions in this simplified version"""
        return False

    def get_signal(self, timestamp: float) -> Optional[bool]:
        """
        Generate trading signals based on market conditions.
        Returns True for long signal, False for short signal, None for no signal.
        """
        # In this simplified version, we'll implement basic signal logic
        # You can extend this with your own signal generation logic
        return None

    def process_order_update(self, event: OrderFilledEvent):
        """Process order updates and manage active positions"""
        super().process_order_update(event)
        if event.trading_pair == self.config.trading_pair:
            logger.info(f"Order filled: {event}")
            # Track position for take profit and trailing stop management
            self._active_positions[event.trading_pair] = {
                "entry_price": event.price,
                "amount": event.amount,
                "trade_type": event.trade_type,
                "take_profit_price": event.price
                * (Decimal("1") + self.config.take_profit_percentage),
                "trailing_stop_activated": False,
                "trailing_stop_price": None,
            }

    def format_status(self) -> str:
        """Format strategy status for display"""
        lines = []
        lines.extend(
            [
                f"Trading pair: {self.config.trading_pair}",
                f"Exchange: {self.config.connector_name}",
                f"Order amount: {self.config.order_amount}",
                f"Take profit: {self.config.take_profit_percentage}%",
                f"Trailing stop activation delta: {self.config.trailing_stop_activation_price_delta}",
                f"Trailing stop trailing delta: {self.config.trailing_stop_trailing_delta}",
                "",
                "Active positions:",
            ]
        )

        for pair, pos in self._active_positions.items():
            lines.append(f"  {pair}: {pos['amount']} @ {pos['entry_price']}")

        return "\n".join(lines)

    def start(self):
        """Start the strategy"""
        super().start()
        logger.info("Rocketman strategy started.")

    def stop(self):
        """Stop the strategy"""
        super().stop()
        logger.info("Rocketman strategy stopped.")
