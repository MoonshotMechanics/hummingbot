import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

REST_URL = "https://public-api.birdeye.so"
CANDLES_ENDPOINT = "/defi/ohlcv"
DEFAULT_API_KEY = "1907b712820c4bbdb4ff8a9dbee55e7c"


async def fetch_birdeye_candles(
    token_address: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    interval: str = "5m",
) -> List[Dict]:
    """
    Fetch candle data from Birdeye API.
    Returns list of candles with OHLCV data.
    """
    try:
        headers = {
            "X-API-KEY": DEFAULT_API_KEY,
            "Accept": "application/json",
            "X-Chain": "solana",
        }

        # Calculate timestamps
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = datetime.fromtimestamp(
                end_time.timestamp() - (3 * 24 * 60 * 60)
            )  # 3 days ago

        params = {
            "address": token_address,
            "type": interval,
            "time_from": int(start_time.timestamp()),
            "time_to": int(end_time.timestamp()),
        }

        logger.info(f"Fetching Birdeye candles with params: {params}")

        async with aiohttp.ClientSession() as session:
            url = f"{REST_URL}{CANDLES_ENDPOINT}"
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"Birdeye API error (status {resp.status}): {error_text}"
                    )
                    return []

                response_json = await resp.json()
                data = response_json.get("data", {})
                items = data.get("items", [])

                logger.info(f"Received {len(items)} candles from Birdeye API")

                # Convert to standardized format
                candles = []
                for item in items:
                    candle = {
                        "timestamp": int(float(item["unixTime"]))
                        * 1000,  # Convert to milliseconds
                        "open": Decimal(str(item["o"])),
                        "high": Decimal(str(item["h"])),
                        "low": Decimal(str(item["l"])),
                        "close": Decimal(str(item["c"])),
                        "volume": Decimal(str(item["v"])),
                        "quote_volume": Decimal("0"),  # Not provided by Birdeye
                        "trades": 0,  # Not provided by Birdeye
                    }
                    candles.append(candle)

                return sorted(candles, key=lambda x: x["timestamp"])

    except Exception as e:
        logger.error(f"Error fetching Birdeye candles: {str(e)}")
        return []
