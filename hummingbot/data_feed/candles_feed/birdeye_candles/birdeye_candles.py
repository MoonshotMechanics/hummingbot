import os
import sys
import time
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
candles_logger = logging.getLogger("birdeye_candles")
candles_logger.setLevel(logging.INFO)
candles_logger.propagate = True  # Allow propagation to root logger

# Create file handler for candles log
log_file = os.path.join(data_path(), "logs", "birdeye_candles.log")
os.makedirs(os.path.dirname(log_file), exist_ok=True)
file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
file_handler.setFormatter(formatter)
candles_logger.addHandler(file_handler)


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
            candles_logger.info("=== Starting new Birdeye candles session ===")

            # Start fetching candles
            self._fetch_task = loop.create_task(self._fetch_and_handle_errors())

        except Exception as e:
            error_msg = f"Error initializing BirdeyeCandles: {str(e)}\n{''.join(traceback.format_tb(e.__traceback__))}"
            self.logger().error(error_msg)
            candles_logger.error(error_msg)
            raise

    def _initialize_db(self):
        try:
            db_path = os.path.join(data_path(), "birdeye_candles.db")
            Session = BirdeyeCandle.create_tables(db_path)
            self._db_session = Session()
        except SQLAlchemyError as e:
            error_msg = f"Database error: {str(e)}\n{''.join(traceback.format_tb(e.__traceback__))}"
            self.logger().error(error_msg)
            candles_logger.error(error_msg)
            raise
        except Exception as e:
            error_msg = f"Error initializing database: {str(e)}\n{''.join(traceback.format_tb(e.__traceback__))}"
            self.logger().error(error_msg)
            candles_logger.error(error_msg)
            raise

    @catch_and_log_errors
    async def _fetch_and_handle_errors(self):
        """Wrapper to handle errors in the async task"""
        await self.fetch_candles()
        self._ready = True

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
        try:
            headers = {
                "X-API-KEY": self._api_key,
                "Accept": "application/json",
                "X-Chain": "solana",
            }

            # Calculate timestamps
            current_time = int(time.time())
            five_days_ago = current_time - (5 * 24 * 60 * 60)

            params = {
                "address": "HbqujJENLP5cnH662jiaKvnbcVR9zz2HWPKRJob1m2s4",
                "type": "5m",
                "time_from": five_days_ago,
                "time_to": current_time,
            }

            self.logger().info(f"Fetching Birdeye candles with params: {params}")
            candles_logger.info(f"Fetching candles with params: {params}")

            async with aiohttp.ClientSession() as session:
                url = f"{CONSTANTS.REST_URL}{CONSTANTS.CANDLES_ENDPOINT}"
                try:
                    async with session.get(url, headers=headers, params=params) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            error_msg = f"Birdeye API error (status {resp.status}): {error_text}"
                            self.logger().error(error_msg)
                            candles_logger.error(error_msg)
                            return []

                        try:
                            response_json = await resp.json()
                        except Exception as e:
                            error_msg = f"Error parsing Birdeye JSON response: {str(e)}\nRaw response: {await resp.text()}"
                            self.logger().error(error_msg)
                            candles_logger.error(error_msg)
                            return []

                        if not isinstance(response_json, dict):
                            error_msg = (
                                f"Unexpected Birdeye response format: {response_json}"
                            )
                            self.logger().error(error_msg)
                            candles_logger.error(error_msg)
                            return []

                        data = response_json.get("data", [])
                        if not data:
                            error_msg = "No candles data in Birdeye response"
                            self.logger().warning(error_msg)
                            candles_logger.warning(error_msg)
                            return []

                        candles_logger.info("\nProcessed Candles:")
                        candles_logger.info(
                            "Timestamp | Open | High | Low | Close | Volume"
                        )
                        candles_logger.info("-" * 60)

                        for candle in data:
                            try:
                                # Log raw candle data for debugging
                                candles_logger.debug(
                                    f"Processing raw candle data: {candle}"
                                )

                                if not isinstance(candle, dict):
                                    tb = traceback.extract_tb(sys.exc_info()[2])
                                    error_msg = (
                                        f"Invalid Birdeye candle format at line {tb[-1].lineno} - "
                                        f"expected dict, got {type(candle)}: {candle}\n"
                                        f"Stack trace:\n{traceback.format_stack()}"
                                    )
                                    self.logger().error(error_msg)
                                    candles_logger.error(error_msg)
                                    continue

                                # Validate required fields exist
                                required_fields = [
                                    "time",
                                    "open",
                                    "high",
                                    "low",
                                    "close",
                                    "volume",
                                ]
                                missing_fields = [
                                    field
                                    for field in required_fields
                                    if field not in candle
                                ]
                                if missing_fields:
                                    tb = traceback.extract_tb(sys.exc_info()[2])
                                    error_msg = (
                                        f"Missing required fields in Birdeye candle data at line {tb[-1].lineno}: "
                                        f"{missing_fields}\nStack trace:\n{traceback.format_stack()}"
                                    )
                                    self.logger().error(error_msg)
                                    candles_logger.error(error_msg)
                                    continue

                                timestamp = int(float(candle.get("time", 0)) * 1000)
                                try:
                                    candle_data = [
                                        timestamp,
                                        float(candle.get("open", 0)),
                                        float(candle.get("high", 0)),
                                        float(candle.get("low", 0)),
                                        float(candle.get("close", 0)),
                                        float(candle.get("volume", 0)),
                                        0.0,  # Quote asset volume
                                        0,  # Number of trades
                                        0.0,  # Taker buy base volume
                                        0.0,  # Taker buy quote volume
                                    ]
                                except ValueError as e:
                                    tb = traceback.extract_tb(sys.exc_info()[2])
                                    error_msg = (
                                        f"Error converting Birdeye candle values to float at line {tb[-1].lineno}: "
                                        f"{str(e)}\nCandle data: {candle}\n"
                                        f"Stack trace:\n{traceback.format_exc()}"
                                    )
                                    self.logger().error(error_msg)
                                    candles_logger.error(error_msg)
                                    continue

                                candles.append(candle_data)

                                readable_time = time.strftime(
                                    "%Y-%m-%d %H:%M:%S",
                                    time.localtime(timestamp / 1000),
                                )
                                candles_logger.info(
                                    f"{readable_time} | {candle.get('open', 0):.4f} | {candle.get('high', 0):.4f} | "
                                    f"{candle.get('low', 0):.4f} | {candle.get('close', 0):.4f} | {candle.get('volume', 0):.2f}"
                                )
                            except (ValueError, TypeError, KeyError) as e:
                                error_msg = f"Error processing candle {candle}: {str(e)}\n{traceback.format_exc()}"
                                self.logger().error(error_msg)
                                candles_logger.error(error_msg)
                                continue

                        candles.sort(key=lambda x: x[0])

                        candles_logger.info(f"\nTotal candles received: {len(candles)}")
                        if len(candles) > 0:
                            first_candle_time = time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.localtime(candles[0][0] / 1000),
                            )
                            last_candle_time = time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.localtime(candles[-1][0] / 1000),
                            )
                            candles_logger.info(
                                f"Time range: {first_candle_time} to {last_candle_time}"
                            )

                        try:
                            for candle in candles:
                                db_candle = BirdeyeCandle(
                                    token_address="HbqujJENLP5cnH662jiaKvnbcVR9zz2HWPKRJob1m2s4",
                                    interval="5m",
                                    timestamp=time.strftime(
                                        "%Y-%m-%d %H:%M:%S",
                                        time.localtime(candle[0] / 1000),
                                    ),
                                    open=candle[1],
                                    high=candle[2],
                                    low=candle[3],
                                    close=candle[4],
                                    volume=candle[5],
                                )
                                self._db_session.merge(db_candle)
                            self._db_session.commit()
                        except SQLAlchemyError as e:
                            error_msg = f"Database error while storing candles: {str(e)}\n{traceback.format_exc()}"
                            self.logger().error(error_msg)
                            candles_logger.error(error_msg)
                            self._db_session.rollback()
                        except Exception as e:
                            error_msg = f"Error storing candles in database: {str(e)}\n{traceback.format_exc()}"
                            self.logger().error(error_msg)
                            candles_logger.error(error_msg)
                            self._db_session.rollback()

                        return candles

                except aiohttp.ClientError as e:
                    error_msg = f"HTTP client error: {str(e)}\n{traceback.format_exc()}"
                    self.logger().error(error_msg)
                    candles_logger.error(error_msg)
                    return []

        except Exception as e:
            error_msg = (
                f"Error fetching historical candles: {str(e)}\n{traceback.format_exc()}"
            )
            self.logger().error(error_msg)
            candles_logger.error(error_msg)
            return []

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
                    candles_logger.error(error_msg)
            candles_logger.info("=== Ending Birdeye candles session ===\n")
        except Exception as e:
            error_msg = (
                f"Error stopping BirdeyeCandles: {str(e)}\n{traceback.format_exc()}"
            )
            self.logger().error(error_msg)
            candles_logger.error(error_msg)
