import asyncio
import json
import os
from datetime import datetime
from typing import List, Optional

import aiohttp
from bidict import bidict

from hummingbot import data_path
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.data_feed.candles_feed.bitquery_candles import constants as CONSTANTS
from hummingbot.data_feed.candles_feed.bitquery_candles.models import BitqueryCandle
from hummingbot.data_feed.candles_feed.candles_base import CandlesBase
from hummingbot.logger import HummingbotLogger

logger = HummingbotLogger(__name__)


class BitqueryCandles(CandlesBase):
    _logger = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._db_session = None
        self._initialize_db()
        self._polling_task = None
        self._last_timestamp = None
        self.logger().info("🔄 Initialized Bitquery candles feed")

    def _initialize_db(self):
        db_path = os.path.join(data_path(), "bitquery_candles.db")
        Session = BitqueryCandle.create_tables(db_path)
        self._db_session = Session()

    @property
    def rate_limits(self):
        return CONSTANTS.RATE_LIMITS

    @property
    def intervals(self) -> bidict:
        return CONSTANTS.INTERVALS

    @property
    def max_records_per_request(self) -> int:
        return CONSTANTS.MAX_RESULTS_PER_CANDLESTICK_REST_REQUEST

    def get_exchange_trading_pair(self, trading_pair: str) -> str:
        return trading_pair

    async def fetch_candles(
        self, start_time: float, end_time: float, limit: Optional[int] = None
    ) -> List[List[float]]:
        """Fetch historical candles for backtesting"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CONSTANTS.BITQUERY_TOKEN}",
        }

        # Format the OHLC query with variables
        query = CONSTANTS.OHLC_QUERY.copy()
        query["variables"].update(
            {
                "token": self._ex_trading_pair,
                "from": datetime.utcfromtimestamp(start_time).isoformat(),
                "till": datetime.utcfromtimestamp(end_time).isoformat(),
                "interval": CONSTANTS.INTERVALS[self.interval]
                // 60,  # Convert seconds to minutes
            }
        )

        if CONSTANTS.DEBUG_LOGGING:
            self.logger().info(
                f"🔍 Fetching historical candles from {start_time} to {end_time}"
            )
            self.logger().info(f"📊 Query: {query}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    CONSTANTS.REST_URL,
                    headers=headers,
                    json=query,
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        self.logger().error(f"❌ API error: {error_text}")
                        return []

                    data = await resp.json()
                    if CONSTANTS.DEBUG_LOGGING:
                        self.logger().info(f"📥 Received data: {data}")

                    trades = data.get("data", {}).get("Solana", {}).get("DEXTrades", [])
                    if not trades:
                        self.logger().info("❌ No trades in response")
                        return []

                    # Convert trades to candles format
                    candles = []
                    for trade in trades:
                        timestamp = int(
                            datetime.strptime(
                                trade["timeInterval"]["minute"], "%Y-%m-%dT%H:%M:%SZ"
                            ).timestamp()
                            * 1000
                        )  # Convert to milliseconds

                        candle = [
                            timestamp,
                            float(trade["priceOpen"]),
                            float(trade["priceHigh"]),
                            float(trade["priceLow"]),
                            float(trade["priceClose"]),
                            float(trade["volume"]),
                            0.0,  # Quote asset volume
                            int(trade["trades"]),  # Number of trades
                            0.0,  # Taker buy base volume
                            0.0,  # Taker buy quote volume
                        ]
                        candles.append(candle)

                    # Sort by timestamp ascending
                    candles.sort(key=lambda x: x[0])
                    return candles

        except Exception as e:
            self.logger().error(
                f"❌ Error fetching historical candles: {str(e)}", exc_info=True
            )
            return []

    async def _start_polling(self):
        """Poll trade data from Bitquery REST API and aggregate into candles"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CONSTANTS.BITQUERY_TOKEN}",
        }

        # Format the trades query with variables
        query = CONSTANTS.TRADES_QUERY.copy()
        query["variables"].update(
            {
                "network": "mainnet",
                "token": self._ex_trading_pair,
            }
        )

        if CONSTANTS.DEBUG_LOGGING:
            self.logger().info(f"🔍 Token address: {self._ex_trading_pair}")
            self.logger().info(f"📊 Interval: {self.interval}")
            self.logger().info(f"📝 Query: {query}")

        last_trade_time = None
        current_candle = None

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        CONSTANTS.REST_URL,
                        headers=headers,
                        json=query,
                    ) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            self.logger().error(f"❌ API error: {error_text}")
                            await asyncio.sleep(5)
                            continue

                        data = await resp.json()
                        if CONSTANTS.DEBUG_LOGGING:
                            self.logger().info(f"📥 Received data: {data}")

                        trades = (
                            data.get("data", {}).get("Solana", {}).get("DEXTrades", [])
                        )
                        if not trades:
                            self.logger().info("❌ No trades in response")
                            await asyncio.sleep(5)
                            continue

                        for trade in trades:
                            timestamp = datetime.strptime(
                                trade["Block"]["Time"], "%Y-%m-%dT%H:%M:%SZ"
                            ).timestamp()

                            # Skip trades we've already processed
                            if last_trade_time and timestamp <= last_trade_time:
                                continue

                            price = float(trade["Trade"]["Price"])
                            amount = float(trade["Trade"]["Amount"])

                            # Calculate candle timestamp (floor to interval)
                            candle_timestamp = int(timestamp) - (
                                int(timestamp) % CONSTANTS.INTERVALS[self.interval]
                            )

                            # If this is a new candle
                            if (
                                current_candle is None
                                or current_candle["timestamp"] != candle_timestamp
                            ):
                                # Send the previous candle if it exists
                                if current_candle is not None:
                                    await self._process_candle(current_candle)

                                # Start new candle
                                current_candle = {
                                    "timestamp": candle_timestamp,
                                    "open": price,
                                    "high": price,
                                    "low": price,
                                    "close": price,
                                    "volume": amount,
                                    "trades": 1,
                                }
                            else:
                                # Update existing candle
                                current_candle["high"] = max(
                                    current_candle["high"], price
                                )
                                current_candle["low"] = min(
                                    current_candle["low"], price
                                )
                                current_candle["close"] = price
                                current_candle["volume"] += amount
                                current_candle["trades"] += 1

                            last_trade_time = timestamp

                # Sleep for a short time before polling again
                await asyncio.sleep(5)  # Poll every 5 seconds for new trades

            except asyncio.CancelledError:
                self.logger().info("🛑 Polling task cancelled")
                raise
            except Exception as e:
                self.logger().error(f"❌ Error polling data: {str(e)}", exc_info=True)
                await asyncio.sleep(5)

    async def _process_candle(self, candle: dict):
        """Process a complete candle"""
        try:
            timestamp = datetime.fromtimestamp(candle["timestamp"])

            db_candle = BitqueryCandle(
                token_address=self._ex_trading_pair,
                interval=self.interval,
                timestamp=timestamp,
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            )

            self._db_session.add(db_candle)
            self._db_session.commit()

            # Convert to the format expected by subscribers
            candle_data = [
                candle["timestamp"] * 1000,  # Timestamp in milliseconds
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
                candle["volume"],
                0.0,  # Quote asset volume
                candle["trades"],  # Number of trades
                0.0,  # Taker buy base volume
                0.0,  # Taker buy quote volume
            ]

            if CONSTANTS.DEBUG_LOGGING:
                self.logger().debug(
                    f"📤 Sending candle data to subscribers: {candle_data}"
                )

            # Notify subscribers
            for callback in self._subscriptions:
                await callback(candle_data)

        except Exception as e:
            self.logger().error(f"❌ Error processing candle: {str(e)}", exc_info=True)

    async def check_network(self) -> NetworkStatus:
        """Check connection to Bitquery API"""
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CONSTANTS.BITQUERY_TOKEN}",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    CONSTANTS.REST_URL,
                    headers=headers,
                    json=CONSTANTS.TEST_QUERY,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "errors" not in data:
                            self.logger().info("✅ Bitquery API connection successful")
                            return NetworkStatus.CONNECTED
                    error_text = await resp.text()
                    self.logger().error(
                        f"❌ Bitquery API returned status {resp.status}"
                    )
                    self.logger().error(f"Error response: {error_text}")
        except Exception as e:
            self.logger().error(f"Error checking network: {str(e)}", exc_info=True)
        return NetworkStatus.NOT_CONNECTED

    async def start_network(self):
        """Start polling for data"""
        if self._polling_task is None:
            self._polling_task = asyncio.create_task(self._start_polling())

    async def stop_network(self):
        """Stop polling"""
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None

    def stop(self):
        if self._db_session:
            self._db_session.close()
        super().stop()
