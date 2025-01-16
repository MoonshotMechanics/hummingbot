import os
import sys
import time
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import traceback
from functools import wraps

# Now do imports
import aiohttp
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional

from hummingbot import data_path
from hummingbot.data_feed.candles_feed.birdeye_candles import constants as CONSTANTS
from hummingbot.data_feed.candles_feed.birdeye_candles.models import BirdeyeCandle
from hummingbot.logger import HummingbotLogger

# Set up specific logger for birdeye candles data
logs_path = os.path.join(data_path(), "logs")
log_file = os.path.join(logs_path, "logs_birdeye_candles.log")
os.makedirs(logs_path, exist_ok=True)

# Create logger
_candles_logger = logging.getLogger("birdeye_candles")
_candles_logger.setLevel(logging.INFO)

# Remove any existing handlers
for handler in _candles_logger.handlers[:]:
    _candles_logger.removeHandler(handler)

# Create file handler with detailed format
file_handler = logging.FileHandler(log_file, mode="a")
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
_candles_logger.addHandler(file_handler)

# Prevent propagation to avoid duplicate logs
_candles_logger.propagate = False

# Test write to ensure logger is working
with open(log_file, "a") as f:
    f.write(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - === Starting new Birdeye candles session ===\n"
    )

# Make logger globally accessible
_candles_logger = _candles_logger


def handle_asyncio_error(loop, context):
    """Global handler for asyncio errors"""
    exception = context.get("exception")
    error_msg = f"Asyncio error: {context.get('message')}"
    if exception:
        error_msg += f"\nException: {exception.__class__.__name__} at line {sys.exc_info()[2].tb_lineno}\n{''.join(traceback.format_tb(exception.__traceback__))}"
    BirdeyeCandles.logger().error(error_msg)  # Use class logger directly


def catch_and_log_errors(func):
    """Decorator to catch and log any errors"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            tb = traceback.extract_tb(sys.exc_info()[2])
            error_msg = (
                f"Error in {func.__name__} at line {tb[-1].lineno}: {str(e)}\n"
                f"Stack trace:\n{''.join(traceback.format_tb(e.__traceback__))}"
            )
            BirdeyeCandles.logger().error(error_msg)  # Use class logger directly
            raise

    return wrapper


class BirdeyeCandles:
    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        trading_pair: str = None,
        interval: str = None,
        max_records: int = None,
        **kwargs,
    ):
        try:
            self._db_session = None
            self._initialize_db()
            self._api_key = CONSTANTS.DEFAULT_API_KEY
            self._trading_pair = trading_pair
            self._interval = interval
            self._max_records = max_records
            self._ready = False
            self._fetch_task = None

            # Set up error handler for the event loop
            loop = asyncio.get_event_loop()
            loop.set_exception_handler(handle_asyncio_error)

            self.logger().info("🔄 Initialized Birdeye historical candles")
            _candles_logger.info("Initializing Birdeye candles feed")

            # Start fetching candles
            self._fetch_task = loop.create_task(self._fetch_and_handle_errors())

        except Exception as e:
            error_msg = f"Error initializing BirdeyeCandles: {str(e)}\n{''.join(traceback.format_tb(e.__traceback__))}"
            self.logger().error(error_msg)
            _candles_logger.error(error_msg)
            raise

    def _initialize_db(self):
        try:
            db_path = os.path.join(data_path(), "birdeye_candles.db")
            Session = BirdeyeCandle.create_tables(db_path)
            self._db_session = Session()
        except SQLAlchemyError as e:
            error_msg = f"Database error: {str(e)}\n{''.join(traceback.format_tb(e.__traceback__))}"
            self.logger().error(error_msg)
            _candles_logger.error(error_msg)
            raise
        except Exception as e:
            error_msg = f"Error initializing database: {str(e)}\n{''.join(traceback.format_tb(e.__traceback__))}"
            self.logger().error(error_msg)
            _candles_logger.error(error_msg)
            raise

    @catch_and_log_errors
    async def _fetch_and_handle_errors(self):
        """Wrapper to handle errors in the async task"""
        candles = await self.fetch_candles()
        # Only mark as ready if we got candle data
        if candles:
            self._ready = True
            self.logger().info(f"Feed ready with {len(candles)} candles")
        else:
            self.logger().warning("Feed not ready - no candle data received")

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    @property
    def ready(self) -> bool:
        return self._ready

    async def fetch_candles(self) -> List[List[float]]:
        """Fetch 5m candles for the last 5 days"""
        candles = []
        session = None
        try:
            headers = {
                "X-API-KEY": self._api_key,
                "Accept": "application/json",
                "X-Chain": "solana",
            }

            # Calculate timestamps
            current_time = int(time.time())
            three_days_ago = current_time - (3 * 24 * 60 * 60)

            params = {
                "address": "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC",
                "type": "5m",
                "time_from": three_days_ago,
                "time_to": current_time,
            }

            self.logger().info(f"Fetching Birdeye candles with params: {params}")

            # Write directly to file for debugging
            with open(log_file, "a") as f:
                f.write(
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Fetching with params: {params}\n"
                )

            session = aiohttp.ClientSession()
            url = f"{CONSTANTS.REST_URL}{CONSTANTS.CANDLES_ENDPOINT}"

            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    error_msg = (
                        f"Birdeye API error (status {resp.status}): {error_text}"
                    )
                    with open(log_file, "a") as f:
                        f.write(
                            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ERROR - {error_msg}\n"
                        )
                    return []

                response_json = await resp.json()
                data = response_json.get("data", {})
                items = data.get("items", [])

                # Write directly to file
                with open(log_file, "a") as f:
                    f.write(
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - === Candles Response ===\n"
                    )
                    f.write(
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Status: {resp.status}\n"
                    )
                    f.write(
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Total items: {len(items)}\n"
                    )

                    if items:
                        for candle in items:
                            log_msg = (
                                f"Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(candle['unixTime'])))} | "
                                f"O: {candle['o']:.4f} | H: {candle['h']:.4f} | L: {candle['l']:.4f} | "
                                f"C: {candle['c']:.4f} | V: {candle['v']:.2f}"
                            )
                            f.write(
                                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - {log_msg}\n"
                            )

                    f.write(
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - === End Candles Response ===\n"
                    )

                # Process candles for return value
                for candle in items:
                    try:
                        timestamp = int(float(candle["unixTime"])) * 1000
                        candle_data = [
                            timestamp,
                            float(candle["o"]),
                            float(candle["h"]),
                            float(candle["l"]),
                            float(candle["c"]),
                            float(candle["v"]),
                            0.0,  # Quote asset volume
                            0,  # Number of trades
                            0.0,  # Taker buy base volume
                            0.0,  # Taker buy quote volume
                        ]
                        candles.append(candle_data)
                    except (ValueError, TypeError, KeyError) as e:
                        with open(log_file, "a") as f:
                            f.write(
                                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ERROR - Error processing candle: {str(e)}\n"
                            )
                        continue

            return candles

        except Exception as e:
            error_msg = (
                f"Error fetching historical candles: {str(e)}\n{traceback.format_exc()}"
            )
            with open(log_file, "a") as f:
                f.write(
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ERROR - {error_msg}\n"
                )
            return []

        finally:
            if session and not session.closed:
                await session.close()

    def stop(self):
        try:
            if self._fetch_task and not self._fetch_task.done():
                self._fetch_task.cancel()
            if self._db_session:
                try:
                    self._db_session.close()
                except SQLAlchemyError as e:
                    error_msg = f"Error closing database session: {str(e)}\n{traceback.format_exc()}"
                    self.logger().error(error_msg)
                    _candles_logger.error(error_msg)
            _candles_logger.info("=== Ending Birdeye candles session ===\n")
        except Exception as e:
            error_msg = (
                f"Error stopping BirdeyeCandles: {str(e)}\n{traceback.format_exc()}"
            )
            self.logger().error(error_msg)
            _candles_logger.error(error_msg)
