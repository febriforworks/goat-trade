import enum
from sqlalchemy import Column, String, Date, BigInteger, Boolean, Numeric, Integer, ForeignKey, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Company(Base):
    __tablename__ = "companies"

    code = Column(String(10), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    listing_date = Column(Date, nullable=True)
    shares = Column(BigInteger, nullable=True)
    listing_board = Column(String(50), nullable=True)
    is_lq45 = Column(Boolean, default=False) # TODO: Deprecated, use IndexMembership table instead
    sector = Column(String(100), nullable=True)
    sub_sector = Column(String(100), nullable=True)
    industry = Column(String(100), nullable=True)

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


class CorporateActionType(enum.Enum):
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    RIGHT_ISSUE = "RIGHT_ISSUE"
    WARRANT = "WARRANT"


class CorporateAction(Base):
    __tablename__ = "corporate_actions"

    id = Column(Integer, primary_key=True, index=True)
    company_code = Column(String(10), ForeignKey("companies.code"), nullable=False, index=True)
    ex_date = Column(Date, nullable=False, index=True)
    action_type = Column(SQLEnum(CorporateActionType), nullable=False)
    ratio = Column(Numeric(15, 4), nullable=True) # e.g., 5 for 1:5 stock split
    value = Column(Numeric(25, 4), nullable=True) # e.g., cash dividend amount

    __table_args__ = (
        UniqueConstraint('company_code', 'ex_date', 'action_type', name='uq_corp_action'),
    )


class IndexMembership(Base):
    __tablename__ = "index_memberships"

    id = Column(Integer, primary_key=True, index=True)
    index_code = Column(String(50), nullable=False, index=True) # e.g., 'LQ45', 'IDX30'
    company_code = Column(String(10), ForeignKey("companies.code"), nullable=False, index=True)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=True, index=True) # Null means currently active

    __table_args__ = (
        UniqueConstraint('index_code', 'company_code', 'start_date', name='uq_index_membership'),
    )


class TradingCalendar(Base):
    __tablename__ = "trading_calendar"

    date = Column(Date, primary_key=True, index=True)
    is_trading_day = Column(Boolean, nullable=False, default=True)
    description = Column(String(255), nullable=True) # e.g., 'Idul Fitri Holiday'


class StockStatus(Base):
    __tablename__ = "stock_statuses"

    id = Column(Integer, primary_key=True, index=True)
    company_code = Column(String(10), ForeignKey("companies.code"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    is_suspended = Column(Boolean, default=False)
    is_uma = Column(Boolean, default=False)
    ara_limit = Column(Numeric(15, 2), nullable=True)
    arb_limit = Column(Numeric(15, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint('company_code', 'date', name='uq_stock_status_date'),
    )


class BenchmarkPrice(Base):
    __tablename__ = "benchmark_prices"

    id = Column(Integer, primary_key=True, index=True)
    index_code = Column(String(50), nullable=False, index=True) # e.g., '^JKSE' for IHSG
    date = Column(Date, nullable=False, index=True)

class ScreenerResult(Base):
    __tablename__ = "screener_results"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    company_code = Column(String(10), ForeignKey("companies.code"), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    trend_ok = Column(Boolean, nullable=False)
    breakout_ok = Column(Boolean, nullable=False)
    volume_ok = Column(Boolean, nullable=False)
    foreign_ok = Column(Boolean, nullable=False)
    close_price = Column(Numeric(15, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint('date', 'company_code', name='uq_screener_result_date'),
    )
