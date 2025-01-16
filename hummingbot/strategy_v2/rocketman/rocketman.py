import asyncio
import logging
import time
from decimal import Decimal
from typing import Dict, List, Optional, Union

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PositionMode, PriceType, TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.data_feed.market_data_provider import MarketDataProvider
from hummingbot.strategy.strategy_v2_base import StrategyV2Base
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, StopExecutorAction
from hummingbot.strategy_v2.rocketman.rocketman_config import RocketmanConfig
from hummingbot.strategy_v2.rocketman.rocketman_controller import RocketmanController

# Hardcoded Birdeye API key and token address
BIRDEYE_API_KEY = "3c4f3db1188046bab20cec81ce430834"
# AI16Z token and pair addresses
AI16Z_TOKEN_ADDRESS = "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC"
AI16Z_USDC_PAIR = "HbqujJENLP5cnH662jiaKvnbcVR9zz2HWPKRJob1m2s4"


class RocketmanStrategy(StrategyV2Base):
    """
    A V2 strategy implementation of the Rocketman trading strategy.
    This strategy uses technical indicators (RSI, Bollinger Bands, EMA) to identify trading opportunities
    and implements a trailing stop mechanism for position management.
    """

    @classmethod
    def init_markets(cls, config: RocketmanConfig):
        cls.markets = {config.connector_name: {config.trading_pair}}
        logging.getLogger(__name__).info(f"🚀 Initialized markets: {cls.markets}")

    def __init__(self, connectors: Dict[str, ConnectorBase], config: RocketmanConfig):
        super().__init__(connectors, config)
        self._config = config
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.INFO)
        self._initialization_task = None
        self._initialized = False
        self._max_initialization_time = 120  # 2 minutes timeout
        self.trading_pair = config.trading_pair

        self._logger.info("🚀 Initializing Rocketman Strategy...")
        self._logger.info(
            f"📊 Config: connector={config.connector_name}, trading_pair={config.trading_pair}"
        )
        self._logger.info(
            f"💰 Trading params: leverage={config.leverage}, order_amount={config.order_amount}"
        )

        # Initialize market data provider and candles
        self._logger.info("📈 Setting up market data provider...")
        self._market_data_provider = MarketDataProvider(self.connectors)

        # Start initialization sequence
        self._initialization_task = asyncio.create_task(self._initialize_strategy())

    async def _initialize_strategy(self):
        """Initialize strategy components sequentially"""
        try:
            # Step 1: Wait for Jupiter connector to be ready
            self._logger.info("🔄 Waiting for Jupiter connector to be ready...")
            await self._wait_for_connector_ready()

            # Step 2: Initialize candles feed
            self._logger.info("🕯️ Initializing candles feed...")
            self.logger().info(
                f"  Initializing feed: connector='birdeye' trading_pair='{self.trading_pair}' interval='1m' max_records=1000"
            )

            # Initialize candles feed with the pair address for price data
            candles_config = CandlesConfig(
                connector="birdeye",
                trading_pair=AI16Z_USDC_PAIR,  # Use the pair address for candles
                interval="1m",
                max_records=1000,
                kwargs={"api_key": BIRDEYE_API_KEY},
            )
            self._market_data_provider.initialize_candles_feed(candles_config)
            await self._wait_for_candles_ready(candles_config)

            # Step 3: Initialize controller
            self._logger.info("🎮 Initializing strategy controller...")
            self._controller = RocketmanController(
                config=self._config,
                market_data_provider=self._market_data_provider,
                actions_queue=asyncio.Queue(),
            )

            self._initialized = True
            self._logger.info("✅ Strategy initialization complete!")

        except asyncio.TimeoutError:
            self._logger.error("❌ Strategy initialization timed out!")
            raise
        except Exception as e:
            self._logger.error(
                f"❌ Error during strategy initialization: {str(e)}", exc_info=True
            )
            raise

    async def _wait_for_connector_ready(self, check_interval: float = 1.0):
        """Wait for Jupiter connector to be fully ready"""
        start_time = time.time()
        connector = self.connectors[self._config.connector_name]

        while time.time() - start_time < self._max_initialization_time:
            if connector.ready:
                self._logger.info("✅ Jupiter connector is ready!")
                return

            self._logger.info("⏳ Waiting for Jupiter connector...")
            status_dict = getattr(connector, "status_dict", {})
            self._logger.info(f"  Status: {status_dict}")

            # Check specific components
            if not status_dict.get("account_balance", False):
                self._logger.info("  Waiting for account balance...")
            if not status_dict.get("network_transaction_fee", False):
                self._logger.info("  Waiting for network fee info...")

            await asyncio.sleep(check_interval)

        raise asyncio.TimeoutError("Jupiter connector initialization timed out!")

    async def _wait_for_candles_ready(
        self, candles_config: CandlesConfig, check_interval: float = 1.0
    ):
        """Wait for candles feed to be ready"""
        start_time = time.time()
        feed_key = f"birdeye_{candles_config.trading_pair}_{candles_config.interval}"

        while time.time() - start_time < self._max_initialization_time:
            feed = self._market_data_provider.candles_feeds.get(feed_key)
            if feed and feed.ready:
                self._logger.info(f"✅ Candles feed ready: {feed_key}")
                if hasattr(feed, "_candles"):
                    self._logger.info(f"  Received {len(feed._candles)} candles")
                return

            self._logger.info(f"⏳ Waiting for candles feed: {feed_key}")
            if feed:
                self._logger.info(f"  Feed status: {feed.ready}")
                # Check initialization state
                if hasattr(feed, "_subscribed"):
                    self._logger.info(f"  Subscribed: {feed._subscribed}")
                if hasattr(feed, "_started"):
                    self._logger.info(f"  Started: {feed._started}")
                if hasattr(feed, "_stopped"):
                    self._logger.info(f"  Stopped: {feed._stopped}")
                if hasattr(feed, "_db_initialized"):
                    self._logger.info(f"  DB Initialized: {feed._db_initialized}")

                # Check for errors
                if hasattr(feed, "_last_error"):
                    self._logger.info(f"  Last error: {feed._last_error}")
                if hasattr(feed, "_initialization_error"):
                    self._logger.info(
                        f"  Initialization error: {feed._initialization_error}"
                    )

                # Check network status
                if hasattr(feed, "network_status"):
                    self._logger.info(f"  Network status: {feed.network_status}")

                # Check internal state
                if hasattr(feed, "_state"):
                    self._logger.info(f"  Internal state: {feed._state}")

                # Try to force start if not started
                if hasattr(feed, "start") and not getattr(feed, "_started", False):
                    self._logger.info("  Attempting to start feed...")
                    try:
                        await feed.start()
                        self._logger.info("  Feed start initiated")
                    except Exception as e:
                        self._logger.error(f"  Failed to start feed: {str(e)}")

            await asyncio.sleep(check_interval)

        raise asyncio.TimeoutError(f"Candles feed initialization timed out: {feed_key}")

    async def _initial_status_check(self):
        """Perform initial status check of all components"""
        try:
            self._logger.info("🔄 Checking connector status...")
            await self._log_market_status()

            self._logger.info("🔄 Checking market data provider status...")
            for feed_key, feed in self._market_data_provider.candles_feeds.items():
                self._logger.info(f"  Feed key: {feed_key}")
                self._logger.info(f"  Feed status: {feed}")
                self._logger.info(f"  Feed ready: {feed.ready}")
                self._logger.info(
                    f"  Feed subscribed: {getattr(feed, '_subscribed', False)}"
                )

                # Check feed configuration
                if hasattr(feed, "_config"):
                    config = feed._config
                    self._logger.info("  Feed configuration:")
                    self._logger.info(f"    Connector: {config.connector}")
                    self._logger.info(f"    Trading pair: {config.trading_pair}")
                    self._logger.info(f"    Interval: {config.interval}")
                    self._logger.info(f"    Max records: {config.max_records}")

                # Check data status
                if hasattr(feed, "_candles"):
                    self._logger.info(f"  Candles count: {len(feed._candles)}")
                if hasattr(feed, "last_received_timestamp"):
                    self._logger.info(f"  Last update: {feed.last_received_timestamp}")
                if hasattr(feed, "_last_processed_timestamp"):
                    self._logger.info(
                        f"  Last processed: {feed._last_processed_timestamp}"
                    )

                # Check rate limits if available
                if hasattr(feed, "rate_limits"):
                    self._logger.info(f"  Rate limits: {feed.rate_limits}")

                # Check any error states
                if hasattr(feed, "_last_error"):
                    self._logger.info(f"  Last error: {feed._last_error}")
                if hasattr(feed, "_initialization_error"):
                    self._logger.info(
                        f"  Initialization error: {feed._initialization_error}"
                    )

            self._logger.info("🔄 Checking controller status...")
            self._logger.info(
                f"  Controller initialized: {self._controller is not None}"
            )
            if self._controller.processed_data:
                self._logger.info("  Processed data:")
                for key, value in self._controller.processed_data.items():
                    self._logger.info(f"    {key}: {value}")
            else:
                self._logger.info("  No processed data available")

        except Exception as e:
            self._logger.error(
                f"❌ Error in initial status check: {str(e)}", exc_info=True
            )

    async def _log_market_status(self):
        """Log detailed market status"""
        for connector_name, connector in self.connectors.items():
            self._logger.info(f"🏦 {connector_name} Status:")
            self._logger.info(f"  - Ready: {connector.ready}")
            if not connector.ready:
                self._logger.info("  - Checking connector status:")
                self._logger.info(f"    - Network: {connector.network_status}")
                self._logger.info(
                    f"    - Ready components: {getattr(connector, 'status_dict', {})}"
                )

                # Check initialization status
                init_status = []
                if hasattr(connector, "_markets_initialized"):
                    init_status.append(f"Markets: {connector._markets_initialized}")
                if hasattr(connector, "_account_balances"):
                    init_status.append(f"Balances: {bool(connector._account_balances)}")
                if hasattr(connector, "_account_available_balances"):
                    init_status.append(
                        f"Available Balances: {bool(connector._account_available_balances)}"
                    )
                if init_status:
                    self._logger.info(
                        f"    - Initialization Status: {', '.join(init_status)}"
                    )

                # Handle trading pairs differently for Gateway connectors
                trading_pairs = getattr(connector, "_trading_pairs", set())
                self._logger.info(f"    - Trading pairs: {trading_pairs}")

                # Check markets initialization
                markets_initialized = getattr(connector, "_markets_initialized", False)
                self._logger.info(f"    - Markets initialized: {markets_initialized}")

                # Check network status
                if hasattr(connector, "_check_network_status"):
                    self._logger.info("    - Running network status check...")
                    try:
                        await connector._check_network_status()
                        self._logger.info("    - Network check completed")
                    except Exception as e:
                        self._logger.error(f"    - Network check failed: {str(e)}")

            # Check specific Jupiter/Gateway properties
            if hasattr(connector, "jupiter_client"):
                self._logger.info("  - Jupiter specific status:")
                try:
                    client = getattr(connector, "jupiter_client")
                    self._logger.info(f"    - Client initialized: {client is not None}")
                    if client:
                        self._logger.info(
                            f"    - Client ready: {getattr(client, 'ready', False)}"
                        )
                        self._logger.info(
                            f"    - Client network: {getattr(client, 'network', None)}"
                        )
                        self._logger.info(
                            f"    - Client connection: {getattr(client, '_connection', None)}"
                        )

                        # Additional Jupiter client details
                        if hasattr(client, "wallet"):
                            wallet = client.wallet
                            self._logger.info(
                                f"    - Wallet connected: {wallet is not None}"
                            )
                            if wallet:
                                self._logger.info(
                                    f"    - Wallet address: {getattr(wallet, 'public_key', None)}"
                                )
                        if hasattr(client, "program_id"):
                            self._logger.info(f"    - Program ID: {client.program_id}")

                        # Check RPC connection
                        if hasattr(client, "_connection"):
                            conn = client._connection
                            self._logger.info(
                                f"    - RPC endpoint: {getattr(conn, '_url', None)}"
                            )
                            self._logger.info(
                                f"    - RPC commitment: {getattr(conn, '_commitment', None)}"
                            )
                except Exception as e:
                    self._logger.error(f"    - Error checking Jupiter client: {str(e)}")

            # Log Gateway specific properties
            if hasattr(connector, "_gateway_config"):
                self._logger.info("  - Gateway configuration:")
                try:
                    config = getattr(connector, "_gateway_config")
                    self._logger.info(f"    - Config: {config}")
                    # Log specific Gateway settings
                    if hasattr(config, "host"):
                        self._logger.info(f"    - Gateway host: {config.host}")
                    if hasattr(config, "port"):
                        self._logger.info(f"    - Gateway port: {config.port}")
                except Exception as e:
                    self._logger.error(f"    - Error checking gateway config: {str(e)}")

            # Check connection details
            self._logger.info("  - Connection details:")
            if hasattr(connector, "_client_config"):
                try:
                    config = getattr(connector, "_client_config")
                    self._logger.info(f"    - Client config: {config}")
                except Exception:
                    pass

    def on_tick(self):
        """
        Main strategy logic executed on each tick:
        - Update controller's processed data (includes current price and signal)
        - Process any pending actions from controller
        - Log status of active executors
        """
        try:
            # Check initialization status
            if not self._initialized:
                self._logger.warning("⚠️ Strategy not fully initialized!")
                if self._initialization_task and not self._initialization_task.done():
                    self._logger.info("🔄 Initialization still in progress...")
                elif self._initialization_task and self._initialization_task.done():
                    # Check if initialization failed
                    try:
                        self._initialization_task.result()
                    except Exception as e:
                        self._logger.error(f"❌ Initialization failed: {str(e)}")
                return

            self._logger.info("🔄 Starting tick processing...")

            # Regular tick processing
            if not self.ready_to_trade:
                self._logger.warning("⚠️ Strategy not ready to trade!")
                self._logger.info("Checking connector status...")
                asyncio.create_task(self._log_market_status())
                return

            # Log market status
            asyncio.create_task(self._log_market_status())

            # Create task for updating processed data
            self._logger.info("📊 Updating processed data...")
            update_task = asyncio.create_task(self._controller.update_processed_data())

            # Process controller actions
            queue_size = self._controller.actions_queue.qsize()
            if queue_size > 0:
                self._logger.info(f"⚡ Processing {queue_size} pending actions...")
                while not self._controller.actions_queue.empty():
                    action = self._controller.actions_queue.get_nowait()
                    self._logger.info(f"🎯 Processing action: {action}")
                    asyncio.create_task(self._controller.process_action(action))

            self._logger.info("✅ Tick processing complete!")

        except Exception as e:
            self._logger.error(f"❌ Error in on_tick: {str(e)}", exc_info=True)

    def create_actions_proposal(self) -> List[CreateExecutorAction]:
        """Create actions based on strategy signals"""
        self._logger.info("🎯 Evaluating signals for action proposal...")
        create_actions = []
        if "signal" in self._controller.processed_data:
            signal = self._controller.processed_data["signal"]
            self._logger.info(f"📊 Current signal: {signal}")
            if signal == 1:  # Buy signal
                mid_price = self._controller.processed_data["current_price"]
                self._logger.info(f"💰 Creating BUY action at price {mid_price}")
                create_actions.append(
                    CreateExecutorAction(
                        executor_config=PositionExecutorConfig(
                            timestamp=self.current_timestamp,
                            connector_name=self._config.connector_name,
                            trading_pair=self._config.trading_pair,
                            side=TradeType.BUY,
                            entry_price=mid_price,
                            amount=self._config.order_amount,
                            triple_barrier_config=self._config.triple_barrier_config,
                            leverage=self._config.leverage,
                        )
                    )
                )
                self._logger.info(f"✅ Created {len(create_actions)} buy actions")
        return create_actions

    def stop_actions_proposal(self) -> List[StopExecutorAction]:
        """Stop actions based on strategy signals"""
        self._logger.info("🛑 Evaluating signals for stop actions...")
        stop_actions = []
        if "signal" in self._controller.processed_data:
            signal = self._controller.processed_data["signal"]
            self._logger.info(f"📊 Current signal for stop evaluation: {signal}")
            if signal == 0:  # Exit signal
                active_executors = self._controller.get_all_executors()
                self._logger.info(
                    f"🔄 Creating stop actions for {len(active_executors)} active executors"
                )
                stop_actions.extend(
                    [StopExecutorAction(executor_id=e.id) for e in active_executors]
                )
                self._logger.info(f"✅ Created {len(stop_actions)} stop actions")
        return stop_actions

    @property
    def active_executors(self):
        """Get all active position executors"""
        executors = self._controller.get_all_executors()
        self._logger.info(f"📊 Active executors count: {len(executors)}")
        return executors

    @property
    def controller(self):
        """Get the strategy's controller"""
        return self._controller

    def format_status(self) -> str:
        """Format the status of the strategy for display."""
        if not self.ready_to_trade:
            status = "⚠️  Market connectors are not ready."
            self._logger.warning(status)
            return status

        lines = []
        lines.extend(
            [
                "",
                "🚀 Strategy Status:",
                f"  Active Executors: {len(self.active_executors)}",
            ]
        )

        if self._controller.processed_data:
            data = self._controller.processed_data
            lines.extend(
                [
                    "",
                    "📊 Market Data:",
                    f"  Current Price: {data.get('current_price')}",
                    f"  RSI: {data.get('rsi')}",
                    f"  Signal: {data.get('signal')}",
                    f"  BB Lower: {data.get('bb_lower')}",
                    f"  BB Upper: {data.get('bb_upper')}",
                    f"  EMA: {data.get('ema')}",
                ]
            )

        status = "\n".join(lines)
        self._logger.info(f"📈 Current Status:\n{status}")
        return status
