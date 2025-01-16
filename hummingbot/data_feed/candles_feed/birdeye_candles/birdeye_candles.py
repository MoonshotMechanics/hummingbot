import os
from typing import List, Optional
import time

import aiohttp
from bidict import bidict

from hummingbot import data_path
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.data_feed.candles_feed.birdeye_candles import constants as CONSTANTS
from hummingbot.data_feed.candles_feed.birdeye_candles.models import BirdeyeCandle
from hummingbot.data_feed.candles_feed.candles_base import CandlesBase
from hummingbot.logger import HummingbotLogger

logger = HummingbotLogger(__name__)


class BirdeyeCandles(CandlesBase):
    _logger = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._db_session = None
        self._initialize_db()
        self._api_key = CONSTANTS.DEFAULT_API_KEY
        self.logger().info("🔄 Initialized Birdeye candles feed")

    def _initialize_db(self):
        db_path = os.path.join(data_path(), "birdeye_candles.db")
        Session = BirdeyeCandle.create_tables(db_path)
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
            "X-API-KEY": self._api_key,
            "Accept": "application/json",
            "X-Chain": "solana",
        }

        params = {
            "address": "HbqujJENLP5cnH662jiaKvnbcVR9zz2HWPKRJob1m2s4",
            "type": CONSTANTS.INTERVALS[self.interval],
            "time_from": int(start_time),  # Unix timestamp in seconds
            "time_to": int(end_time),  # Unix timestamp in seconds
        }

        if CONSTANTS.DEBUG_LOGGING:
            self.logger().info(
                f"🔍 Fetching historical candles from {start_time} to {end_time}"
            )
            self.logger().info(f"📊 Params: {params}")

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{CONSTANTS.REST_URL}{CONSTANTS.CANDLES_ENDPOINT}"
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        self.logger().error(f"❌ API error: {error_text}")
                        return []

                    data = await resp.json()
                    if CONSTANTS.DEBUG_LOGGING:
                        self.logger().info(f"📥 Received data: {data}")

                    if not data.get("data", []):
                        self.logger().info("❌ No candles in response")
                        return []

                    # Convert candles to required format
                    candles = []
                    for candle in data["data"]:
                        timestamp = int(
                            candle["time"] * 1000
                        )  # Convert to milliseconds
                        candle_data = [
                            timestamp,
                            float(candle["open"]),
                            float(candle["high"]),
                            float(candle["low"]),
                            float(candle["close"]),
                            float(candle["volume"]),
                            0.0,  # Quote asset volume
                            0,  # Number of trades
                            0.0,  # Taker buy base volume
                            0.0,  # Taker buy quote volume
                        ]
                        candles.append(candle_data)

                    # Sort by timestamp ascending
                    candles.sort(key=lambda x: x[0])
                    return candles

        except Exception as e:
            self.logger().error(
                f"❌ Error fetching historical candles: {str(e)}", exc_info=True
            )
            return []

    async def check_network(self) -> NetworkStatus:
        """Check connection to Birdeye API"""
        try:
            headers = {
                "X-API-KEY": self._api_key,
                "Accept": "application/json",
                "X-Chain": "solana",
            }

            # Get current time and 1 interval ago
            current_time = int(time.time())  # Unix timestamp in seconds
            interval_minutes = int(self.interval[:-1])  # Remove 'm' and convert to int
            start_time = current_time - (interval_minutes * 60)  # Go back one interval

            params = {
                "address": "HbqujJENLP5cnH662jiaKvnbcVR9zz2HWPKRJob1m2s4",
                "type": CONSTANTS.INTERVALS[self.interval],
                "time_from": start_time,
                "time_to": current_time,
            }

            async with aiohttp.ClientSession() as session:
                url = f"{CONSTANTS.REST_URL}{CONSTANTS.CANDLES_ENDPOINT}"
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        self.logger().info("✅ Birdeye API connection successful")
                        return NetworkStatus.CONNECTED
                    error_text = await resp.text()
                    self.logger().error(f"❌ Birdeye API returned status {resp.status}")
                    self.logger().error(f"Error response: {error_text}")
        except Exception as e:
            self.logger().error(f"Error checking network: {str(e)}", exc_info=True)
        return NetworkStatus.NOT_CONNECTED

    async def start_network(self):
        """No need to start network for historical data"""
        pass

    async def stop_network(self):
        """No need to stop network for historical data"""
        pass

    def stop(self):
        if self._db_session:
            self._db_session.close()
        super().stop()
