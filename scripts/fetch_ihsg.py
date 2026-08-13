import sys
import os
import yfinance as yf
import pandas as pd
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db.database import SessionLocal
from app.db.models import BenchmarkPrice

def fetch_ihsg(days="5y"):
    db = SessionLocal()
    try:
        print(f"Fetching IHSG (^JKSE) data for {days}...")
        ticker = yf.Ticker("^JKSE")
        df = ticker.history(period=days)
        
        if df.empty:
            print("No data received from yfinance.")
            return

        records = []
        for index, row in df.iterrows():
            # index is datetime with timezone, convert to date
            date_val = index.date()
            record = BenchmarkPrice(
                index_code="^JKSE",
                date=date_val,
                open_price=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"])
            )
            # Use merge to handle duplicates
            db.merge(record)
            
        db.commit()
        print(f"Successfully updated IHSG data up to {df.index.max().date()}.")
    except Exception as e:
        print(f"Error fetching IHSG: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    fetch_ihsg()
