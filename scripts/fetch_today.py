import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from app.db.database import SessionLocal, init_db
from app.core.timezone import get_jakarta_now
from scripts.fetch_past_daily import fetch_daily_data_idx_by_date

def fetch_today_data():
    init_db()
    db = SessionLocal()
    try:
        today = get_jakarta_now()
        
        # Bursa tutup di akhir pekan
        if today.weekday() >= 5:
            print("Hari ini adalah akhir pekan (Sabtu/Minggu). Bursa tutup.")
            return
            
        date_str_correct = today.strftime('%Y%m%d')
        print(f"Mulai mengambil data harian IDX untuk hari ini (End of Day WIB): {date_str_correct}")
        
        fetch_daily_data_idx_by_date(db, date_str_correct)
        
        print("Selesai mengambil data harian untuk hari ini!")
    finally:
        db.close()

if __name__ == "__main__":
    fetch_today_data()
