import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db.database import engine
from app.db.models import Base
from sqlalchemy import text

with engine.begin() as conn:
    print("Altering benchmark_prices table...")
    try:
        conn.execute(text("ALTER TABLE benchmark_prices ADD COLUMN IF NOT EXISTS open_price NUMERIC(25, 4)"))
        conn.execute(text("ALTER TABLE benchmark_prices ADD COLUMN IF NOT EXISTS high NUMERIC(25, 4)"))
        conn.execute(text("ALTER TABLE benchmark_prices ADD COLUMN IF NOT EXISTS low NUMERIC(25, 4)"))
        conn.execute(text("ALTER TABLE benchmark_prices ADD COLUMN IF NOT EXISTS close NUMERIC(25, 4)"))
        conn.execute(text("ALTER TABLE benchmark_prices ADD COLUMN IF NOT EXISTS volume BIGINT"))
    except Exception as e:
        print(f"Error altering benchmark_prices: {e}")
        
    print("Altering screener_results table...")
    try:
        conn.execute(text("ALTER TABLE screener_results ADD COLUMN IF NOT EXISTS transaction_value NUMERIC(35, 4)"))
        conn.execute(text("ALTER TABLE screener_results ADD COLUMN IF NOT EXISTS stop_loss NUMERIC(15, 2)"))
        conn.execute(text("ALTER TABLE screener_results ADD COLUMN IF NOT EXISTS atr NUMERIC(15, 4)"))
        conn.execute(text("ALTER TABLE screener_results ADD COLUMN IF NOT EXISTS risk_pct NUMERIC(10, 4)"))
    except Exception as e:
        print(f"Error altering screener_results: {e}")

print("Recreating missing tables...")
Base.metadata.create_all(bind=engine)
print("Done!")
