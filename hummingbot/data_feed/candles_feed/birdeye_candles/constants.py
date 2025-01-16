from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit

REST_URL = "https://public-api.birdeye.so"
CANDLES_ENDPOINT = "/defi/ohlcv"

# API key configuration
DEFAULT_API_KEY = "1907b712820c4bbdb4ff8a9dbee55e7c"

# Debug mode for extra logging
DEBUG_LOGGING = True

INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

MAX_RESULTS_PER_CANDLESTICK_REST_REQUEST = 1000
ALL_ENDPOINTS_LIMIT = "All"

RATE_LIMITS = [
    RateLimit(ALL_ENDPOINTS_LIMIT, limit=10, time_interval=1),
    RateLimit(
        CANDLES_ENDPOINT,
        limit=10,
        time_interval=1,
        linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)],
    ),
]
