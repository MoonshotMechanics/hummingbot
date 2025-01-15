#!/usr/bin/env python

import asyncio
import logging
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import Field

from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.trade_fee import TradeFeeSchema
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    MarketOrderFailureEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    SellOrderCompletedEvent,
)
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import (
    PositionExecutorConfig,
    TrailingStop,
    TripleBarrierConfig,
)


class TrailingStopControllerConfig(DirectionalTradingControllerConfigBase):
    controller_name: str = "trailing_stop"

    # Candles configuration
    candles_config: List[CandlesConfig] = Field(
        default=[],  # Will be initialized in the controller
        client_data=ClientFieldData(prompt_on_new=False),
    )
    candles_interval: str = Field(
        default="1m",
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the candle interval (e.g., 1m, 5m, 1h): ",
            prompt_on_new=True,
        ),
    )

    # Strategy-specific parameters
    trailing_stop_activation_price_delta: Decimal = Field(
        default=Decimal("0.01"),  # 1% profit to activate trailing stop
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the trailing stop activation price delta (e.g., 0.01 for 1%): ",
            prompt_on_new=True,
        ),
    )
    trailing_stop_trailing_delta: Decimal = Field(
        default=Decimal("0.005"),  # 0.5% trailing stop
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the trailing stop trailing delta (e.g., 0.005 for 0.5%): ",
            prompt_on_new=True,
        ),
    )
    order_amount: Decimal = Field(
        default=Decimal("0.1"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the order amount: ", prompt_on_new=True
        ),
    )


class TrailingStopController(DirectionalTradingControllerBase):
    def __init__(self, config: TrailingStopControllerConfig, *args, **kwargs):
        # Initialize candles config if not set
        if len(config.candles_config) == 0:
            config.candles_config = [
                CandlesConfig(
                    connector=config.connector_name,
                    trading_pair=config.trading_pair,
                    interval=config.candles_interval,
                    max_records=100,  # Keep last 100 candles
                )
            ]
        super().__init__(config, *args, **kwargs)
        self.config = config
        self._executors = []  # List to store position executors
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.INFO)

    def get_all_executors(self):
        """Return all position executors."""
        return self._executors

    def filter_executors(self, executors, filter_func):
        """Filter executors based on the provided filter function."""
        return [executor for executor in executors if filter_func(executor)]

    async def create_position_executor(self, config):
        """Create a new position executor and store it."""
        executor = await super().create_position_executor(config)
        if executor:
            self._executors.append(executor)
        return executor

    async def update_processed_data(self):
        """Update the processed data based on the current state of the strategy."""
        try:
            # Get the Gateway connector
            connector = self.market_data_provider.connectors[self.config.connector_name]

            # Get current price using Gateway's quote price method
            current_price = await connector.get_quote_price(
                self.config.trading_pair,
                is_buy=True,
                amount=Decimal("1"),
            )

            if current_price is None:
                self._logger.error("Failed to get current price")
                return

            # Default signal is 0 (no action)
            signal = 0

            # Get candles data for analysis if available
            try:
                candles_df = self.market_data_provider.get_candles_df(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    interval=self.config.candles_interval,
                )

                if not candles_df.empty:
                    # Add technical indicators
                    candles_df.ta.rsi(length=14, append=True)
                    candles_df.ta.bbands(length=20, std=2, append=True)
                    candles_df.ta.ema(length=14, append=True)

                    # Get latest indicator values
                    latest_rsi = candles_df["RSI_14"].iloc[-1]
                    latest_bb_lower = candles_df["BBL_20_2.0"].iloc[-1]
                    latest_bb_upper = candles_df["BBU_20_2.0"].iloc[-1]
                    latest_ema = candles_df["EMA_14"].iloc[-1]

                    # Check for buy conditions only if no active positions
                    active_executors = self.get_all_executors()
                    if not active_executors:
                        if (
                            latest_rsi < 30
                            and current_price < latest_bb_lower
                            and current_price < latest_ema
                        ):
                            signal = 1  # Generate buy signal
                            self._logger.info(
                                "Buy signal generated based on technical analysis"
                            )
                            self._logger.info(f"RSI: {latest_rsi:.2f}")
                            self._logger.info(f"BB Lower: {latest_bb_lower:.6f}")
                            self._logger.info(f"EMA: {latest_ema:.6f}")
            except Exception as e:
                self._logger.warning(f"Error processing candles data: {str(e)}")
                # Continue with just price data if candles are not available

            self.processed_data = {
                "current_price": current_price,
                "signal": signal,
            }
        except Exception as e:
            self._logger.error(f"Error updating processed data: {str(e)}")

    def determine_executor_actions(self) -> List[Dict]:
        """Determine what actions to take based on the processed data."""
        if not self.processed_data:
            return []

        actions = []
        signal = self.processed_data["signal"]
        current_price = self.processed_data["current_price"]

        if signal != 0:
            # Create a new position executor
            trade_type = TradeType.SELL if signal < 0 else TradeType.BUY
            executor_config = self.get_executor_config(
                trade_type=trade_type,
                price=current_price,
                amount=self.config.order_amount,
            )
            actions.append(
                {
                    "action": "create_position_executor",
                    "executor_config": executor_config,
                }
            )

        return actions

    def get_executor_config(
        self, trade_type: TradeType, price: Decimal, amount: Decimal
    ) -> PositionExecutorConfig:
        """Create a position executor config with our trailing stop parameters."""
        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            side=trade_type,
            entry_price=price,
            amount=amount,
            leverage=self.config.leverage,
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=None,  # No stop loss, using trailing stop instead
                take_profit=None,  # No take profit, using trailing stop instead
                time_limit=None,  # No time limit
                trailing_stop=TrailingStop(
                    activation_price=self.config.trailing_stop_activation_price_delta,
                    trailing_delta=self.config.trailing_stop_trailing_delta,
                ),
                open_order_type=OrderType.MARKET,
                take_profit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
                time_limit_order_type=OrderType.MARKET,
            ),
        )


class NativeTrailingStop(ScriptStrategyBase):
    markets = {"jupiter_solana_mainnet-beta": {"ai16z-USDC"}}

    def __init__(self, connectors: Dict[str, Dict[str, str]]):
        super().__init__(connectors)
        # Initialize logger correctly
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.INFO)

        # Configure rate oracle source
        from hummingbot.core.rate_oracle.rate_oracle import (
            RATE_ORACLE_SOURCES,
            RateOracle,
        )

        rate_oracle = RateOracle.get_instance()
        rate_oracle.source = RATE_ORACLE_SOURCES["ascend_ex"]()

        # Strategy parameters
        self.trading_pair = "ai16z-USDC"
        self.connector_name = "jupiter_solana_mainnet-beta"

        # Add trading rules to the connector
        self._add_trading_rules_to_connector()

        # Create controller config
        self.controller_config = TrailingStopControllerConfig(
            id="trailing_stop_1",
            controller_name="trailing_stop",
            connector_name=self.connector_name,
            trading_pair=self.trading_pair,
            order_amount=Decimal("0.1"),  # Amount of AI16Z to trade
            trailing_stop_activation_price_delta=Decimal(
                "0.01"
            ),  # 1% profit to activate trailing stop
            trailing_stop_trailing_delta=Decimal("0.005"),  # 0.5% trailing stop
            leverage=1,  # No leverage for spot trading
            candles_interval="1m",  # 1-minute candles
        )

        # Create market data provider
        self.market_data_provider = self.create_market_data_provider()

        # Create controller
        self.controller = TrailingStopController(
            config=self.controller_config,
            market_data_provider=self.market_data_provider,
            actions_queue=asyncio.Queue(),
        )

        # Initialize performance metrics
        self.total_trades = 0
        self.successful_trades = 0
        self.failed_trades = 0

    def _add_trading_rules_to_connector(self):
        """Add trading rules to the connector since Gateway doesn't provide them"""
        connector = self.connectors[self.connector_name]
        if not hasattr(connector, "trading_rules"):
            connector.trading_rules = {}
        if not hasattr(connector, "_trade_fee_schema"):
            connector._trade_fee_schema = TradeFeeSchema()

        # Create trading rule for our trading pair
        trading_rule = TradingRule(
            trading_pair=self.trading_pair,
            min_order_size=Decimal("0.001"),  # Minimum order size
            min_price_increment=Decimal("0.000001"),  # 6 decimal places
            min_base_amount_increment=Decimal("0.001"),  # 3 decimal places
            min_quote_amount_increment=Decimal("0.01"),  # 2 decimal places
            min_notional_size=Decimal("0.1"),  # Minimum notional size in quote currency
        )

        # Add trading rule to connector
        connector.trading_rules[self.trading_pair] = trading_rule

    def create_market_data_provider(self):
        """Create a market data provider for the controller"""
        from hummingbot.data_feed.market_data_provider import MarketDataProvider

        # Create market data provider first
        market_data_provider = MarketDataProvider(
            self.connectors,
        )

        # Initialize candles feed for each config
        for candles_config in self.controller_config.candles_config:
            market_data_provider.initialize_candles_feed(candles_config)

        return market_data_provider

    @property
    def candles_ready(self) -> bool:
        """Check if all candle feeds are ready"""
        return all(
            self.market_data_provider.is_ready(config)
            for config in self.controller_config.candles_config
        )

    async def on_start(self):
        """Called when the strategy starts."""
        self._logger.info("Strategy starting...")
        self.controller.start()

    async def on_stop(self):
        """Called when the strategy stops."""
        self._logger.info("Strategy stopping...")
        self.controller.stop()
        # Stop all candle feeds
        for config in self.controller_config.candles_config:
            self.market_data_provider.stop_candles_feed(config)

    async def on_tick(self):
        """Called every tick (1 second by default)"""
        try:
            if not self.markets_ready:
                self._logger.warning("Markets not ready. Please wait...")
                return

            # Log current state
            self._logger.info("\n=== TICK START ===")

            # Update controller's processed data
            await self.controller.update_processed_data()
            self._logger.info(
                f"Signal: {self.controller.processed_data.get('signal', 0)}"
            )
            self._logger.info(
                f"Current price: {self.controller.processed_data.get('current_price', 'N/A')}"
            )

            # Process any pending actions from the controller
            while not self.controller.actions_queue.empty():
                action = await self.controller.actions_queue.get()
                if action["action"] == "create_position_executor":
                    await self.controller.create_position_executor(
                        action["executor_config"]
                    )

            # Get active executors - this is synchronous
            active_executors = self.controller.filter_executors(
                executors=self.controller.get_all_executors(),
                filter_func=lambda e: e.is_active,
            )

            # Log executor status
            if active_executors:
                for executor in active_executors:
                    try:
                        self._logger.info(f"Active executor {executor.id}:")
                        self._logger.info(f"  Side: {executor.side}")
                        self._logger.info(f"  Amount: {executor.config.amount}")
                        self._logger.info(f"  Entry price: {executor.entry_price}")
                        self._logger.info(
                            f"  Current price: {executor.current_price if executor.current_price else 'N/A'}"
                        )
                        self._logger.info(
                            f"  Net PnL %: {executor.get_net_pnl_pct():.2%}"
                        )
                        if executor._trailing_stop_trigger_pct:
                            self._logger.info(
                                f"  Trailing stop trigger: {executor._trailing_stop_trigger_pct:.2%}"
                            )
                    except Exception as e:
                        self._logger.error(
                            f"Error processing executor {executor.id}: {str(e)}"
                        )
            else:
                self._logger.info("No active executors")

            self._logger.info("=== TICK END ===\n")
        except Exception as e:
            self._logger.error(f"Error in on_tick: {str(e)}")

    def did_complete_buy_order(self, event: BuyOrderCompletedEvent):
        """Called when a buy order is completed."""
        self.successful_trades += 1
        self.total_trades += 1
        self._logger.info(f"Buy order completed - Order ID: {event.order_id}")
        self._logger.info(f"  Amount: {event.base_asset_amount}, Price: {event.price}")
        self._logger.info(f"  Fee: {event.fee_amount} {event.fee_asset}")
        self.notify_hb_app_with_timestamp(
            f"Buy order completed - Amount: {event.base_asset_amount}, Price: {event.price}"
        )

    def did_complete_sell_order(self, event: SellOrderCompletedEvent):
        """Called when a sell order is completed."""
        self.successful_trades += 1
        self.total_trades += 1
        self._logger.info(f"Sell order completed - Order ID: {event.order_id}")
        self._logger.info(f"  Amount: {event.base_asset_amount}, Price: {event.price}")
        self._logger.info(f"  Fee: {event.fee_amount} {event.fee_asset}")
        self.notify_hb_app_with_timestamp(
            f"Sell order completed - Amount: {event.base_asset_amount}, Price: {event.price}"
        )

    def did_fail_order(self, event: MarketOrderFailureEvent):
        """Called when an order fails."""
        self.failed_trades += 1
        self.total_trades += 1
        self._logger.error(f"Order failed - Order ID: {event.order_id}")
        self._logger.error(f"  Error: {event.message}")
        self.notify_hb_app_with_timestamp(f"Order failed - {event.message}")

    def did_cancel_order(self, event: OrderCancelledEvent):
        """Called when an order is cancelled."""
        self._logger.info(f"Order cancelled - Order ID: {event.order_id}")
        self.notify_hb_app_with_timestamp(
            f"Order cancelled - Order ID: {event.order_id}"
        )

    def did_fill_order(self, event: OrderFilledEvent):
        """Called when an order is filled (partially or fully)."""
        self._logger.info(f"Order filled - Order ID: {event.order_id}")
        self._logger.info(f"  Amount: {event.amount}, Price: {event.price}")
        self._logger.info(f"  Fee: {event.fee.amount} {event.fee.token}")
        self.notify_hb_app_with_timestamp(
            f"Order filled - Amount: {event.amount}, Price: {event.price}"
        )

    def format_status(self) -> str:
        """Format status for display"""
        lines = []
        lines.append("=== Native Trailing Stop Status ===")

        # Show performance metrics
        lines.extend(
            [
                "\n=== Performance Metrics ===",
                f"Total trades: {self.total_trades}",
                f"Successful trades: {self.successful_trades}",
                f"Failed trades: {self.failed_trades}",
                f"Success rate: {(self.successful_trades / self.total_trades * 100):.1f}%"
                if self.total_trades > 0
                else "Success rate: N/A",
            ]
        )

        # Show candles status
        if self.candles_ready:
            lines.extend(["\n=== Market Data ==="])
            for config in self.controller_config.candles_config:
                candles_df = self.market_data_provider.get_candles_df(
                    connector_name=config.connector,
                    trading_pair=config.trading_pair,
                    interval=config.interval,
                )
                if not candles_df.empty:
                    # Add technical indicators
                    candles_df.ta.rsi(length=14, append=True)
                    candles_df.ta.bbands(length=20, std=2, append=True)
                    candles_df.ta.ema(length=14, append=True)

                    lines.extend(
                        [
                            f"\nCandles: {config.connector} {config.trading_pair}",
                            f"Interval: {config.interval}",
                            "Latest indicators:",
                            f"  RSI(14): {candles_df['RSI_14'].iloc[-1]:.2f}",
                            f"  BB Upper: {candles_df['BBU_20_2.0'].iloc[-1]:.6f}",
                            f"  BB Lower: {candles_df['BBL_20_2.0'].iloc[-1]:.6f}",
                            f"  EMA(14): {candles_df['EMA_14'].iloc[-1]:.6f}",
                        ]
                    )
        else:
            lines.extend(["\nCandles data not ready yet"])

        # Show active executors
        active_executors = self.controller.filter_executors(
            executors=self.controller.get_all_executors(),
            filter_func=lambda e: e.is_active,
        )

        if active_executors:
            lines.extend(["\n=== Active Executors ==="])
            for executor in active_executors:
                lines.extend(
                    [
                        f"\nExecutor {executor.id}:",
                        f"  Side: {executor.side}",
                        f"  Amount: {executor.config.amount}",
                        f"  Entry price: {executor.entry_price}",
                        f"  Current price: {executor.current_price}",
                        f"  Net PnL %: {executor.get_net_pnl_pct():.2%}",
                    ]
                )
                if executor._trailing_stop_trigger_pct:
                    lines.append(
                        f"  Trailing stop trigger: {executor._trailing_stop_trigger_pct:.2%}"
                    )
        else:
            lines.extend(["\nNo active executors"])

        return "\n".join(lines)

    @property
    def markets_ready(self) -> bool:
        """Check if markets are ready for trading"""
        return all(market.ready for market in self.connectors.values())

    async def check_initial_balance(self):
        """Check if we have enough balance to start the strategy."""
        base_token = self.trading_pair.split("-")[0]
        quote_token = self.trading_pair.split("-")[1]

        # Get balances through connector
        connector = self.market_data_provider.connectors[self.config.connector_name]
        balances = await connector.get_all_balances()

        if balances:
            base_balance = Decimal(str(balances.get(base_token, 0)))
            quote_balance = Decimal(str(balances.get(quote_token, 0)))

            self._logger.info(
                f"Initial balances: {base_balance} {base_token}, {quote_balance} {quote_token}"
            )

            if base_balance > 0:
                self.initial_position = base_balance
                self.current_position = base_balance
                return True
            else:
                self._logger.error(
                    f"Insufficient {base_token} balance to start strategy."
                )
                return False
        else:
            self._logger.error("Failed to get balances.")
            return False

    async def get_current_price(self) -> Optional[Decimal]:
        """Get current price from market data provider."""
        try:
            current_price = self.market_data_provider.get_price_by_type(
                self.config.connector_name, self.config.trading_pair, PriceType.MidPrice
            )
            return current_price
        except Exception as e:
            self._logger.error(f"Error getting price: {str(e)}")
            return None

    async def execute_trade(self, side: str, amount: Decimal) -> bool:
        """Execute a trade through the position executor."""
        try:
            # Get current price
            current_price = await self.get_current_price()
            if not current_price:
                self._logger.error("Failed to get current price for trade execution")
                return False

            # Create executor config
            trade_type = TradeType.SELL if side.upper() == "SELL" else TradeType.BUY
            executor_config = self.get_executor_config(
                trade_type=trade_type, price=current_price, amount=amount
            )

            # Create and start position executor
            executor = await self.controller.create_position_executor(executor_config)
            if executor:
                self._logger.info(f"Created position executor {executor.id}")
                return True
            else:
                self._logger.error("Failed to create position executor")
                return False

        except Exception as e:
            self._logger.error(f"Error executing trade: {str(e)}")
            return False

    def tick(self, timestamp: float):
        """Clock tick entry point"""
        if not self.ready_to_trade:
            self.ready_to_trade = all(ex.ready for ex in self.connectors.values())
            if not self.ready_to_trade:
                for con in [c for c in self.connectors.values() if not c.ready]:
                    self._logger.warning(f"{con.name} is not ready. Please wait...")
                return

        asyncio.create_task(self.on_tick())
