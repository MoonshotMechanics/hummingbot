import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.rocketman_v2.configs.rocketman_config import RocketmanConfig
from hummingbot.strategy_v2.rocketman_v2.utils.backtesting_utils import BacktestingUtils

logger = logging.getLogger(__name__)


class BacktestingExecutor:
    """
    Executes backtests for the Rocketman strategy using historical candle data from Birdeye
    """

    def __init__(self, config: RocketmanConfig):
        self.config = config
        self.utils = BacktestingUtils()

    async def run_backtest(
        self,
        token_address: str,
        start_time: datetime,
        end_time: datetime,
        trade_type: TradeType,
        entry_price: Optional[Decimal] = None,
        interval: str = "5m",
    ) -> Dict:
        """
        Run a backtest for the strategy over the specified time period
        """
        # Load historical candles from Birdeye
        candles = await self.utils.load_candles(
            token_address=token_address,
            start_time=start_time,
            end_time=end_time,
            interval=interval,
        )

        if not candles:
            logger.error("No candles found for backtesting")
            return {}

        # Use first candle price if entry price not specified
        if entry_price is None:
            entry_price = Decimal(str(candles[0]["close"]))

        # Simulate the position
        position, events = self.utils.simulate_position(
            candles=candles,
            entry_price=entry_price,
            amount=self.config.order_amount,
            trade_type=trade_type,
            take_profit_percentage=self.config.take_profit_percentage,
            trailing_stop_activation_delta=self.config.trailing_stop_activation_price_delta,
            trailing_stop_trailing_delta=self.config.trailing_stop_trailing_delta,
        )

        # Analyze results
        results = self.utils.analyze_backtest_results(events)

        # Add strategy configuration to results
        results.update(
            {
                "config": {
                    "token_address": token_address,
                    "interval": interval,
                    "order_amount": str(self.config.order_amount),
                    "take_profit_percentage": str(self.config.take_profit_percentage),
                    "trailing_stop_activation_delta": str(
                        self.config.trailing_stop_activation_price_delta
                    ),
                    "trailing_stop_trailing_delta": str(
                        self.config.trailing_stop_trailing_delta
                    ),
                    "trade_type": trade_type.name,
                    "entry_price": str(entry_price),
                }
            }
        )

        return results

    async def run_parameter_optimization(
        self,
        token_address: str,
        start_time: datetime,
        end_time: datetime,
        trade_type: TradeType,
        take_profit_range: List[Decimal],
        trailing_stop_activation_range: List[Decimal],
        trailing_stop_trailing_range: List[Decimal],
        interval: str = "5m",
    ) -> List[Dict]:
        """
        Run multiple backtests with different parameter combinations to find optimal settings
        """
        results = []
        total_combinations = (
            len(take_profit_range)
            * len(trailing_stop_activation_range)
            * len(trailing_stop_trailing_range)
        )
        current = 0

        # Load candles once for all tests
        candles = await self.utils.load_candles(
            token_address=token_address,
            start_time=start_time,
            end_time=end_time,
            interval=interval,
        )

        if not candles:
            logger.error("No candles found for parameter optimization")
            return results

        entry_price = Decimal(str(candles[0]["close"]))

        # Test all parameter combinations
        for tp in take_profit_range:
            for tsa in trailing_stop_activation_range:
                for tst in trailing_stop_trailing_range:
                    current += 1
                    logger.info(f"Testing combination {current}/{total_combinations}")

                    # Create temporary config with current parameters
                    temp_config = RocketmanConfig(
                        connector_name=self.config.connector_name,
                        trading_pair=self.config.trading_pair,
                        order_amount=self.config.order_amount,
                        take_profit_percentage=tp,
                        trailing_stop_activation_price_delta=tsa,
                        trailing_stop_trailing_delta=tst,
                    )

                    # Simulate position with current parameters
                    position, events = self.utils.simulate_position(
                        candles=candles,
                        entry_price=entry_price,
                        amount=temp_config.order_amount,
                        trade_type=trade_type,
                        take_profit_percentage=tp,
                        trailing_stop_activation_delta=tsa,
                        trailing_stop_trailing_delta=tst,
                    )

                    # Analyze results
                    test_results = self.utils.analyze_backtest_results(events)
                    test_results.update(
                        {
                            "parameters": {
                                "take_profit_percentage": str(tp),
                                "trailing_stop_activation_delta": str(tsa),
                                "trailing_stop_trailing_delta": str(tst),
                            }
                        }
                    )
                    results.append(test_results)

        # Sort results by final PnL percentage
        results.sort(key=lambda x: float(x["final_pnl_percentage"]), reverse=True)
        return results

    def format_backtest_results(self, results: Dict) -> str:
        """Format backtest results for display"""
        if not results:
            return "No backtest results available"

        lines = [
            "Backtest Results:",
            "================",
            f"Token Address: {results['config']['token_address']}",
            f"Interval: {results['config']['interval']}",
            f"Trade Type: {results['config']['trade_type']}",
            f"Entry Price: {results['config']['entry_price']}",
            f"Order Amount: {results['config']['order_amount']}",
            "",
            "Strategy Parameters:",
            f"Take Profit: {results['config']['take_profit_percentage']}",
            f"Trailing Stop Activation: {results['config']['trailing_stop_activation_delta']}",
            f"Trailing Stop Delta: {results['config']['trailing_stop_trailing_delta']}",
            "",
            "Performance Metrics:",
            f"Final PnL: {results['final_pnl']}",
            f"Final PnL %: {results['final_pnl_percentage']}%",
            f"Max PnL: {results['max_pnl']}",
            f"Min PnL: {results['min_pnl']}",
            f"Max Drawdown: {results['max_drawdown']}",
            f"Exit Reason: {results['exit_reason']}",
            f"Duration: {results['end_timestamp'] - results['start_timestamp']}",
        ]

        return "\n".join(lines)
