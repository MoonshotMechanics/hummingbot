from bidict import bidict

from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit

REST_URL = "https://graphql.bitquery.io"
WSS_URL = "wss://streaming.bitquery.io/graphql"

# API key configuration
BITQUERY_TOKEN = "ory_at_Iyj-5_xs81e8YsQXid4PKqZPhJGs-mvy8fw7DSc4ewE.vWNnJ3-YGa0HGgycxXJrbjppjszJOV0QPJQPBUD3YPc"

# Debug mode for extra logging
DEBUG_LOGGING = True

INTERVALS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

MAX_RESULTS_PER_CANDLESTICK_REST_REQUEST = 1000
ALL_ENDPOINTS_LIMIT = "All"

RATE_LIMITS = [
    RateLimit(ALL_ENDPOINTS_LIMIT, limit=10, time_interval=1),
]

# OHLC query template for REST API
OHLC_QUERY = {
    "query": """
    query ($network: SolanaNetwork!, $token: String!, $from: ISO8601DateTime, $till: ISO8601DateTime, $interval: Int!) {
      Solana(network: $network) {
        DEXTrades(
          options: {desc: "Block_Time", limit: 100}
          where: {
            Trade: {
              Currency: {SmartContract: {is: $token}},
              Side: {Currency: {SmartContract: {is: "So11111111111111111111111111111111111111112"}}}
            }
            Block: {Time: {since: $from, till: $till}}
          }
          interval: {in: minutes, count: $interval}
        ) {
          timeInterval {
            minute(count: $interval)
          }
          volume: tradeAmount
          trades: count
          priceOpen: minimum(of: Block_Time, get: Trade_Price)
          priceHigh: maximum(of: Trade_Price)
          priceLow: minimum(of: Trade_Price)
          priceClose: maximum(of: Block_Time, get: Trade_Price)
        }
      }
    }
    """,
    "variables": {
        "network": "mainnet",
        "token": "",  # Will be filled in at runtime
        "from": "",  # Will be filled in at runtime
        "till": "",  # Will be filled in at runtime
        "interval": 1,  # Will be set based on interval parameter
    },
}

# For network check
TEST_QUERY = {
    "query": """
    query {
      Solana(network: mainnet) {
        DEXTrades(options: {limit: 1}) {
          Block {
            Time
          }
        }
      }
    }
    """,
    "variables": {},
}

# Query for recent trades
TRADES_QUERY = {
    "query": """
    query ($network: SolanaNetwork!, $token: String!) {
      Solana(network: $network) {
        DEXTrades(
          options: {desc: "Block_Time", limit: 100}
          where: {
            Trade: {
              Currency: {SmartContract: {is: $token}},
              Side: {Currency: {SmartContract: {is: "So11111111111111111111111111111111111111112"}}}
            }
          }
        ) {
          Block {
            Time
          }
          Trade {
            Price
            Amount
          }
        }
      }
    }
    """,
    "variables": {
        "network": "mainnet",
        "token": "",  # Will be filled in at runtime
    },
}
