from app.db.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print("FREN in companies:", db.scalar(text("SELECT count(*) FROM companies WHERE code='FREN'")))
print("FREN in daily:", db.scalar(text("SELECT count(*) FROM daily_market_data WHERE company_code='FREN'")))
print("FREN in hist:", db.scalar(text("SELECT count(*) FROM historical_prices WHERE company_code='FREN'")))
db.close()
