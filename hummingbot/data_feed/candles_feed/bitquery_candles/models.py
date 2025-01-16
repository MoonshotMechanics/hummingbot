from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class BitqueryCandle(Base):
    __tablename__ = "bitquery_candles"

    id = Column(Integer, primary_key=True)
    token_address = Column(String)
    interval = Column(String)
    timestamp = Column(DateTime)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)

    @staticmethod
    def create_tables(db_path: str):
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)

    def to_list(self) -> list:
        return [
            int(self.timestamp.timestamp()),
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            0.0,  # quote_asset_volume
            0,  # number of trades
            0.0,  # taker_buy_base_volume
            0.0,  # taker_buy_quote_volume
        ]
