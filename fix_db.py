from app.db.database import engine
from app.db.models import Base, DailyMarketData

# Drop the table
print("Dropping daily_market_data table...")
DailyMarketData.__table__.drop(engine)

# Recreate the table
print("Recreating daily_market_data table...")
Base.metadata.create_all(bind=engine)
print("Done!")
