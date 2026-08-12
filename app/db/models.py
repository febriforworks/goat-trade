from sqlalchemy import Column, String, Date, BigInteger, Boolean, Numeric, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Company(Base):
    __tablename__ = "companies"

    code = Column(String(10), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    listing_date = Column(Date, nullable=True)
    shares = Column(BigInteger, nullable=True)
    listing_board = Column(String(50), nullable=True)
    is_lq45 = Column(Boolean, default=False)

class HistoricalPrice(Base):
    __tablename__ = "historical_prices"

    id = Column(Integer, primary_key=True, index=True)
    company_code = Column(String(10), ForeignKey("companies.code"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    previous = Column(Numeric(15, 2), nullable=True)
    open_price = Column(Numeric(15, 2), nullable=True)
    high = Column(Numeric(15, 2), nullable=True)
    low = Column(Numeric(15, 2), nullable=True)
    close = Column(Numeric(15, 2), nullable=False)
    change = Column(Numeric(15, 2), nullable=True)
    volume = Column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint('company_code', 'date', name='uq_company_date_hist'),
    )

class DailyMarketData(Base):
    __tablename__ = "daily_market_data"

    id = Column(Integer, primary_key=True, index=True)
    company_code = Column(String(10), ForeignKey("companies.code"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Detailed IDX fields
    previous = Column(Numeric(25, 4), nullable=True)
    open_price = Column(Numeric(25, 4), nullable=True)
    first_trade = Column(Numeric(25, 4), nullable=True)
    high = Column(Numeric(25, 4), nullable=True)
    low = Column(Numeric(25, 4), nullable=True)
    close = Column(Numeric(25, 4), nullable=True)
    change = Column(Numeric(25, 4), nullable=True)
    volume = Column(BigInteger, nullable=True)
    value = Column(Numeric(35, 4), nullable=True)
    frequency = Column(BigInteger, nullable=True)
    index_individual = Column(Numeric(25, 4), nullable=True)
    offer = Column(Numeric(25, 4), nullable=True)
    offer_volume = Column(BigInteger, nullable=True)
    bid = Column(Numeric(25, 4), nullable=True)
    bid_volume = Column(BigInteger, nullable=True)
    listed_shares = Column(BigInteger, nullable=True)
    tradeble_shares = Column(BigInteger, nullable=True)
    weight_for_index = Column(Numeric(35, 4), nullable=True)
    foreign_sell = Column(BigInteger, nullable=True)
    foreign_buy = Column(BigInteger, nullable=True)
    delisting_date = Column(Date, nullable=True)
    non_regular_volume = Column(BigInteger, nullable=True)
    non_regular_value = Column(Numeric(35, 4), nullable=True)
    non_regular_frequency = Column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint('company_code', 'date', name='uq_company_date_daily'),
    )
