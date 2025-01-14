#!/usr/bin/env python

import asyncio
import logging
from decimal import Decimal
from typing import Dict, Optional

from hummingbot.core.clock import Clock
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.event.event_forwarder import EventForwarder
from hummingbot.core.event.events import MarketEvent, OrderFilledEvent
from hummingbot.core.gateway.gateway_http_client import GatewayHttpClient
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class ai16zTrailingStop(ScriptStrategyBase):
    markets = {"jupiter_solana_mainnet-beta": {"ai16z-USDC"}}

    def __init__(self, connectors: Dict[str, Dict[str, str]]):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)  # Set to INFO to see all important logs
        self.logger.info("Initializing ai16z Trailing Stop Strategy...")

        super().__init__(connectors)

        # Strategy parameters
        self.trading_pair = "ai16z-USDC"  # Using symbols for display
        # Token mint addresses
        self.base_token_address = "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC"  # Replace with actual ai16z mint address
        self.quote_token_address = (
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC mint address
        )
        self.connector_name = "jupiter_solana_mainnet-beta"
        self.trailing_stop_pct = Decimal("0.001")  # 0.1% trailing stop for testing
        self.max_slippage_pct = Decimal("0.01")  # 1% maximum slippage for market orders

        # Get market connector
        self.market = list(self.connectors.values())[0]

        # State variables
        self.highest_observed_price = Decimal("0")
        self.stop_price = Decimal("0")
        self.is_tracking = False
        self.stop_loss_triggered = False

        # Position tracking
        self.current_position = Decimal("0")
        self.total_pnl = Decimal("0")

        # Set up event listeners
        self.init_event_listeners()

        self.logger.info("=== Strategy Configuration ===")
        self.logger.info(f"Trading pair: {self.trading_pair}")
        self.logger.info(f"Trailing stop percentage: {self.trailing_stop_pct * 100}%")
        self.logger.info(f"Maximum slippage: {self.max_slippage_pct * 100}%")
        self.logger.info("============================")

        # Add initial balance check
        asyncio.create_task(self.check_initial_balance())

    def init_event_listeners(self):
        """Initialize event listeners for order updates"""
        try:
            self.logger.info("Initializing event listeners...")
            self.sell_fill_forwarder = EventForwarder(self._sell_filled_event)
            self.buy_fill_forwarder = EventForwarder(self._buy_filled_event)

            # Use MarketEvent enum values directly
            self.market.add_listener(MarketEvent.OrderFilled, self.sell_fill_forwarder)
            self.market.add_listener(MarketEvent.OrderFilled, self.buy_fill_forwarder)
            self.market.add_listener(
                MarketEvent.SellOrderCompleted, self.sell_fill_forwarder
            )
            self.market.add_listener(
                MarketEvent.BuyOrderCompleted, self.buy_fill_forwarder
            )
            self.logger.info("Event listeners initialized successfully")
        except Exception as e:
            self.logger.error(
                f"Error initializing event listeners: {str(e)}", exc_info=True
            )

    async def check_initial_balance(self):
        """Check if we have enough balance to start the strategy."""
        base_token = self.trading_pair.split("-")[0]
        quote_token = self.trading_pair.split("-")[1]

        # Get balances through Gateway instance
        balances = await self.market._get_gateway_instance().get_balances(
            self.market.chain,
            self.market.network,
            self.market.address,
            [base_token, quote_token],
        )

        if balances and "balances" in balances:
            base_balance = Decimal(str(balances["balances"].get(base_token, 0)))
            quote_balance = Decimal(str(balances["balances"].get(quote_token, 0)))

            self.logger.info(
                f"Initial balances: {base_balance} {base_token}, {quote_balance} {quote_token}"
            )

            if base_balance > 0:
                self.initial_position = base_balance
                self.current_position = base_balance
                return True
            else:
                self.logger.error(
                    f"Insufficient {base_token} balance to start strategy."
                )
                return False
        else:
            self.logger.error("Failed to get balances.")
            return False

    @property
    def markets_ready(self) -> bool:
        """Check if markets are ready to trade"""
        ready = all(market.ready for market in self.connectors.values())
        if not ready:
            self.logger.info("Markets not ready for trading")
        return ready

    async def on_tick(self):
        """Called every tick (1 second by default)"""
        if not self.markets_ready:
            return

        self.logger.info("\n=== TICK START ===")
        self.logger.info(f"Current position: {self.current_position} ai16z")
        self.logger.info(f"Total realized value: {self.total_pnl} USDC")

        # Get current market price using connector
        try:
            # Parse connector info
            connector, chain, network = self.connector_name.split("_")

            # Get price directly through Gateway client
            try:
                # Convert 0.1 to proper decimal scaling (8 decimals for Solana tokens)
                # amount = Decimal("0.1") * Decimal("10") ** 8  # 10000000 (0.1 SOL)

                # Get sell price since we're selling AI16Z for USDC
                sell_price_response = await GatewayHttpClient.get_instance().get_price(
                    "solana",
                    "mainnet-beta",
                    "jupiter",
                    "ai16z",
                    "USDC",
                    Decimal("0.1"),
                    TradeType.SELL,
                )

                # Log raw price response for debugging
                self.logger.info(f"Raw price response: {sell_price_response}")

                if sell_price_response and "price" in sell_price_response:
                    current_price = Decimal(str(sell_price_response["price"]))
                    self.logger.info(
                        f"Current price: {current_price:.6f} USDC per AI16Z"
                    )

                    if not self.is_tracking:
                        self.start_tracking(current_price)
                    else:
                        self.logger.info(
                            f"Highest price: {self.highest_observed_price} USDC"
                        )
                        self.logger.info(f"Stop price: {self.stop_price} USDC")
                        self.update_trailing_stop(current_price)
                else:
                    self.logger.warning("Failed to get valid price response")

            except Exception as price_error:
                self.logger.error(f"Price fetch error: {str(price_error)}")
                return

        except Exception as e:
            self.logger.error(f"Error in on_tick: {str(e)}")
        finally:
            self.logger.info("=== TICK END ===\n")

    def start_tracking(self, current_price: Decimal):
        """Start tracking the price for trailing stop"""
        self.highest_observed_price = current_price
        self.stop_price = current_price * (Decimal("1") - self.trailing_stop_pct)
        self.is_tracking = True

        self.logger.info("Starting price tracking...")
        self.logger.info(f"Initial price: {self.highest_observed_price} USDC")
        self.logger.info(f"Initial stop price: {self.stop_price} USDC")

    def update_trailing_stop(self, current_price: Decimal):
        """Update trailing stop based on current price"""
        if self.stop_loss_triggered:
            return

        # Check if stop loss triggered
        if current_price <= self.stop_price:
            self.logger.warning("!!! STOP LOSS TRIGGERED !!!")
            self.logger.warning(
                f"Current price ({current_price}) <= Stop price ({self.stop_price})"
            )
            self.stop_loss_triggered = True
            asyncio.create_task(self.execute_stop_loss(current_price))
            return

        # Update highest price and stop price if we have a new high
        if current_price > self.highest_observed_price:
            old_stop = self.stop_price
            self.highest_observed_price = current_price
            self.stop_price = current_price * (Decimal("1") - self.trailing_stop_pct)

            self.logger.info("New high price detected")
            self.logger.info(
                f"New stop price: {self.stop_price} USDC (was: {old_stop} USDC)"
            )

    async def execute_stop_loss(self, current_price: Decimal):
        """Execute the stop loss order using market connector"""
        self.logger.warning("=== EXECUTING STOP LOSS ===")
        self.logger.warning(f"Current price: {current_price} USDC per AI16Z")

        try:
            # Get current balance through Gateway instance
            base_token = self.trading_pair.split("-")[0]
            quote_token = self.trading_pair.split("-")[1]

            balances = await self.market._get_gateway_instance().get_balances(
                self.market.chain,
                self.market.network,
                self.market.address,
                [base_token, quote_token],
            )

            if balances and "balances" in balances:
                base_balance = Decimal(str(balances["balances"].get(base_token, 0)))
                quote_balance = Decimal(str(balances["balances"].get(quote_token, 0)))
                self.logger.info(f"Current {base_token} balance: {base_balance}")
                self.logger.info(f"Current {quote_token} balance: {quote_balance}")

                if base_balance > Decimal("0"):
                    # Calculate test amount (5% of balance)
                    amount = base_balance * Decimal("0.05")
                    self.logger.info(f"Selling {amount} {base_token}")

                    # Calculate expected output
                    expected_output = amount * current_price
                    self.logger.info(
                        f"Expected output: {expected_output} {quote_token}"
                    )

                    # Calculate minimum acceptable price with slippage
                    min_acceptable_price = current_price * (
                        Decimal("1") - self.max_slippage_pct
                    )
                    self.logger.info(
                        f"Minimum acceptable price: {min_acceptable_price} {quote_token} per {base_token}"
                    )

                    # Calculate minimum expected output with slippage
                    min_expected_output = amount * min_acceptable_price
                    self.logger.info(
                        f"Minimum expected output (with {self.max_slippage_pct * 100}% slippage): {min_expected_output} {quote_token}"
                    )

                    try:
                        # Place market sell order
                        self.logger.info("Placing market sell order...")
                        order_id = self.market.sell(
                            trading_pair=self.trading_pair,
                            amount=amount,
                            order_type=OrderType.MARKET,
                            price=min_acceptable_price,
                        )
                        self.logger.info(f"Order placed with ID: {order_id}")

                        # Wait a bit to see if order is filled
                        await asyncio.sleep(5)

                        # Check if order was filled by checking balance again
                        new_balances = (
                            await self.market._get_gateway_instance().get_balances(
                                self.market.chain,
                                self.market.network,
                                self.market.address,
                                [base_token, quote_token],
                            )
                        )

                        if new_balances and "balances" in new_balances:
                            new_base_balance = Decimal(
                                str(new_balances["balances"].get(base_token, 0))
                            )
                            new_quote_balance = Decimal(
                                str(new_balances["balances"].get(quote_token, 0))
                            )
                            self.logger.info("Balance after order:")
                            self.logger.info(
                                f"New {base_token} balance: {new_base_balance}"
                            )
                            self.logger.info(
                                f"New {quote_token} balance: {new_quote_balance}"
                            )

                            # Calculate actual output
                            base_sold = base_balance - new_base_balance
                            quote_received = new_quote_balance - quote_balance

                            if base_sold > 0:
                                actual_price = quote_received / base_sold
                                self.logger.info("Order filled:")
                                self.logger.info(
                                    f"Amount sold: {base_sold} {base_token}"
                                )
                                self.logger.info(
                                    f"Amount received: {quote_received} {quote_token}"
                                )
                                self.logger.info(
                                    f"Actual price: {actual_price} {quote_token} per {base_token}"
                                )
                                self.logger.info(
                                    f"Price slippage: {((current_price - actual_price) / current_price * 100):.4f}%"
                                )
                            else:
                                self.logger.warning(
                                    "Order might not have been filled (balance unchanged)"
                                )

                    except Exception as order_error:
                        self.logger.error(
                            f"Error placing order: {str(order_error)}", exc_info=True
                        )
                else:
                    self.logger.warning(
                        f"No {base_token} balance available for stop loss."
                    )
            else:
                self.logger.error("Failed to get balances for stop loss execution.")

        except Exception as e:
            self.logger.error(f"Error executing stop loss: {str(e)}", exc_info=True)

    def _sell_filled_event(self, event: OrderFilledEvent):
        """Handle sell order filled events"""
        self.logger.info("=== SELL ORDER FILLED ===")
        self.logger.info(f"Order ID: {event.order_id}")
        self.logger.info(f"Amount: {event.amount}")
        self.logger.info(f"Price: {event.price}")
        self.logger.info(f"Fee: {event.trade_fee}")

        # Update position
        self.current_position -= event.amount

        # Calculate realized value instead of PnL since we don't have an entry price
        realized_value = event.amount * event.price
        self.total_pnl += realized_value  # This is now tracking total realized value

        self.logger.info("=== Trade Summary ===")
        self.logger.info(f"Amount sold: {event.amount} ai16z")
        self.logger.info(f"Sale price: {event.price} USDC")
        self.logger.info(f"Realized value: {realized_value} USDC")
        self.logger.info(f"Total realized value: {self.total_pnl} USDC")
        self.logger.info(f"Remaining position: {self.current_position} ai16z")
        self.logger.info("======================")

    def _buy_filled_event(self, event: OrderFilledEvent):
        """Handle buy order filled events"""
        self.logger.info("=== BUY ORDER FILLED ===")
        self.logger.info(f"Order ID: {event.order_id}")
        self.logger.info(f"Amount: {event.amount}")
        self.logger.info(f"Price: {event.price}")
        self.logger.info(f"Fee: {event.trade_fee}")
        self.logger.info("=======================")

    def format_status(self) -> str:
        """Format status for display in Hummingbot"""
        if not self.markets_ready:
            return "Market connectors are not ready."

        lines = []
        lines.append("=== ai16z Trailing Stop Status ===")
        lines.append(f"Trading pair: {self.trading_pair}")
        lines.append(f"Highest observed price: {self.highest_observed_price}")
        lines.append(f"Current stop price: {self.stop_price}")
        lines.append(f"Trailing stop %: {self.trailing_stop_pct * 100}%")
        lines.append(f"Current position: {self.current_position} ai16z")
        lines.append(f"Total realized value: {self.total_pnl} USDC")
        lines.append("===============================")

        return "\n".join(lines)

    def stop(self, clock: Optional[Clock] = None):
        """Called when the strategy is stopped - cleanup"""
        self.logger.info("Stopping strategy - cleaning up...")
        try:
            self.market.remove_listener(
                MarketEvent.OrderFilled, self.sell_fill_forwarder
            )
            self.market.remove_listener(
                MarketEvent.OrderFilled, self.buy_fill_forwarder
            )
            self.market.remove_listener(
                MarketEvent.SellOrderCompleted, self.sell_fill_forwarder
            )
            self.market.remove_listener(
                MarketEvent.BuyOrderCompleted, self.buy_fill_forwarder
            )
            self.logger.info("Event listeners removed successfully")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}", exc_info=True)
        finally:
            super().stop(clock)
            self.logger.info("Strategy stopped")

    def tick(self, timestamp: float):
        """Clock tick entry point"""
        asyncio.create_task(self.on_tick())
