import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Tuple

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.rocketman_v2.models.position_state import PositionState
from hummingbot.strategy_v2.rocketman_v2.utils.birdeye_api import fetch_birdeye_candles

logger = logging.getLogger(__name__)


class BacktestingUtils:
    """Utility class for backtesting with Birdeye candles"""

    @staticmethod
    async def load_candles(
        token_address: str,
        start_time: datetime,
        end_time: datetime,
        interval: str = "5m",
    ) -> List[Dict]:
        """Load candles from Birdeye API for backtesting"""
        try:
            candles = await fetch_birdeye_candles(
                token_address=token_address,
                start_time=start_time,
                end_time=end_time,
                interval=interval,
            )
            logger.info(f"Loaded {len(candles)} candles for backtesting")
            return candles
        except Exception as e:
            logger.error(f"Error loading candles: {str(e)}")
            return []

    @staticmethod
    def simulate_position(
        candles: List[Dict],
        entry_price: Decimal,
        amount: Decimal,
        trade_type: TradeType,
        take_profit_percentage: Decimal,
        trailing_stop_activation_delta: Decimal,
        trailing_stop_trailing_delta: Decimal,
    ) -> Tuple[PositionState, List[Dict]]:
        """
        Simulate a position through historical candles and track performance
        Returns the final position state and a list of trade events
        """
        if not candles:
            return None, []

        events = []
        position = PositionState(
            trading_pair=candles[0].get("trading_pair", "UNKNOWN"),
            trade_type=trade_type,
            entry_price=entry_price,
            amount=amount,
            current_price=entry_price,
            take_profit_price=entry_price * (1 + take_profit_percentage),
            trailing_stop_activation_price=trailing_stop_activation_delta,
        )

        for candle in candles:
            # Update position with new price
            position.update_price(Decimal(str(candle["close"])))

            # Check for take profit
            if position.should_take_profit():
                events.append(
                    {
                        "timestamp": candle["timestamp"],
                        "type": "take_profit",
                        "price": position.current_price,
                        "pnl": position.unrealized_pnl,
                        "pnl_percentage": position.unrealized_pnl_percentage,
                    }
                )
                break

            # Check for trailing stop
            if position.should_stop_loss():
                events.append(
                    {
                        "timestamp": candle["timestamp"],
                        "type": "trailing_stop",
                        "price": position.current_price,
                        "pnl": position.unrealized_pnl,
                        "pnl_percentage": position.unrealized_pnl_percentage,
                    }
                )
                break

            # Track position state
            events.append(
                {
                    "timestamp": candle["timestamp"],
                    "type": "update",
                    "price": position.current_price,
                    "pnl": position.unrealized_pnl,
                    "pnl_percentage": position.unrealized_pnl_percentage,
                    "trailing_stop_activated": position.is_trailing_stop_activated,
                    "trailing_stop_price": position.trailing_stop_price,
                }
            )

        return position, events

    @staticmethod
    def analyze_backtest_results(events: List[Dict]) -> Dict:
        """Analyze backtest results and return performance metrics"""
        if not events:
            return {}

        metrics = {
            "start_timestamp": events[0]["timestamp"],
            "end_timestamp": events[-1]["timestamp"],
            "final_pnl": events[-1]["pnl"],
            "final_pnl_percentage": events[-1]["pnl_percentage"],
            "max_pnl": max(event["pnl"] for event in events),
            "min_pnl": min(event["pnl"] for event in events),
            "max_drawdown": 0,
            "exit_reason": events[-1]["type"],
        }

        # Calculate maximum drawdown
        peak = float("-inf")
        max_drawdown = 0
        for event in events:
            pnl = float(event["pnl"])
            peak = max(peak, pnl)
            drawdown = peak - pnl
            max_drawdown = max(max_drawdown, drawdown)
        metrics["max_drawdown"] = max_drawdown

        return metrics
