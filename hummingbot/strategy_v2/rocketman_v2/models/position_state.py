from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from hummingbot.core.data_type.common import TradeType


@dataclass
class PositionState:
    """
    Tracks the state of a position including entry price, current price,
    trailing stop and take profit levels.
    """

    trading_pair: str
    trade_type: TradeType
    entry_price: Decimal
    amount: Decimal
    current_price: Decimal
    take_profit_price: Decimal
    trailing_stop_activation_price: Decimal
    trailing_stop_price: Optional[Decimal] = None
    is_trailing_stop_activated: bool = False

    def update_price(self, new_price: Decimal) -> None:
        """
        Update current price and adjust trailing stop if activated
        """
        self.current_price = new_price

        # Check if trailing stop should be activated
        if not self.is_trailing_stop_activated:
            price_change = (
                (new_price - self.entry_price) / self.entry_price
                if self.trade_type == TradeType.BUY
                else (self.entry_price - new_price) / self.entry_price
            )
            if price_change >= self.trailing_stop_activation_price:
                self.is_trailing_stop_activated = True
                self.trailing_stop_price = new_price

        # Update trailing stop price if activated
        if self.is_trailing_stop_activated and self.trailing_stop_price is not None:
            if self.trade_type == TradeType.BUY:
                self.trailing_stop_price = max(self.trailing_stop_price, new_price)
            else:
                self.trailing_stop_price = min(self.trailing_stop_price, new_price)

    def should_take_profit(self) -> bool:
        """Check if take profit level is reached"""
        if self.trade_type == TradeType.BUY:
            return self.current_price >= self.take_profit_price
        return self.current_price <= self.take_profit_price

    def should_stop_loss(self) -> bool:
        """Check if trailing stop level is reached"""
        if not self.is_trailing_stop_activated or self.trailing_stop_price is None:
            return False

        if self.trade_type == TradeType.BUY:
            return self.current_price <= self.trailing_stop_price
        return self.current_price >= self.trailing_stop_price

    @property
    def unrealized_pnl(self) -> Decimal:
        """Calculate unrealized PnL"""
        price_diff = self.current_price - self.entry_price
        if self.trade_type == TradeType.SELL:
            price_diff = -price_diff
        return price_diff * self.amount

    @property
    def unrealized_pnl_percentage(self) -> Decimal:
        """Calculate unrealized PnL as percentage"""
        return (self.unrealized_pnl / (self.entry_price * self.amount)) * Decimal("100")
