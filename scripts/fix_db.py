import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db.database import engine
from app.db.models import Base
from sqlalchemy import text

# Add new columns to companies table if they don't exist
with engine.begin() as conn:
    print("Altering companies table...")
    try:
        conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS sector VARCHAR(100)"))
        conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS sub_sector VARCHAR(100)"))
        conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS industry VARCHAR(100)"))
    except Exception as e:
        print(f"Error altering table: {e}")

# Recreate all tables (this will create the new ones like CorporateAction without dropping existing ones)
print("Recreating missing tables...")
Base.metadata.create_all(bind=engine)
print("Done!")
