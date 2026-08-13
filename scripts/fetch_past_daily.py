import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cloudscraper
import json
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from time import sleep

from app.db.database import SessionLocal
from app.db.models import Company, DailyMarketData

def fetch_daily_data_idx_by_date(db: Session, target_date: str):
    """
    Fetch IDX summary for a specific date.
    target_date format: YYYYMMDD
    """
    http = cloudscraper.CloudScraper()
    link = f"https://idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0&date={target_date}"
    
    try:
        response = http.get(link)
        if response.status_code != 200:
            print(f"[{target_date}] HTTP {response.status_code}: {response.text}")
            return
        result = json.loads(response.text)
    except Exception as e:
        print(f"[{target_date}] Error fetching data: {e}")
        return
        
    data_list = result.get("data", [])
    if not data_list:
        print(f"[{target_date}] Data kosong dari IDX (mungkin hari libur bursa).")
        return
        
    records_to_insert = []
    existing_companies = {c.code for c in db.query(Company).all()}
    
    for data in data_list:
        code = data.get("StockCode")
        if not code or code not in existing_companies: 
            continue
        
        try:
            trade_date = datetime.strptime(data['Date'], '%Y-%m-%dT%H:%M:%S').date()
        except Exception:
            trade_date = pd.to_datetime(data['Date']).date()
            
        exists = db.query(DailyMarketData).filter(
            DailyMarketData.company_code == code,
            DailyMarketData.date == trade_date
        ).first()
        
        if not exists:
            record = DailyMarketData(
                company_code=code,
                date=trade_date,
                previous=data.get('Previous'),
                open_price=data.get('OpenPrice'),
                first_trade=data.get('FirstTrade'),
                high=data.get('High'),
                low=data.get('Low'),
                close=data.get('Close'),
                change=data.get('Change'),
                volume=data.get('Volume'),
                value=data.get('Value'),
                frequency=data.get('Frequency'),
                index_individual=data.get('IndexIndividual'),
                offer=data.get('Offer'),
                offer_volume=data.get('OfferVolume'),
                bid=data.get('Bid'),
                bid_volume=data.get('BidVolume'),
                listed_shares=data.get('ListedShares'),
                tradeble_shares=data.get('TradebleShares'),
                weight_for_index=data.get('WeightForIndex'),
                foreign_sell=data.get('ForeignSell'),
                foreign_buy=data.get('ForeignBuy'),
                delisting_date=pd.to_datetime(data['DelistingDate']).date() if data.get('DelistingDate') else None,
                non_regular_volume=data.get('NonRegularVolume'),
                non_regular_value=data.get('NonRegularValue'),
                non_regular_frequency=data.get('NonRegularFrequency')
            )
            records_to_insert.append(record)
            
    if records_to_insert:
        db.bulk_save_objects(records_to_insert)
        db.commit()
        print(f"[{target_date}] Successfully saved {len(records_to_insert)} records.")
    else:
        print(f"[{target_date}] No new records to insert (already exist or no matching active companies).")

def fetch_past_days(days=10):
    db = SessionLocal()
    try:
        today = datetime.now()
        print(f"Mulai mengambil data historis harian IDX untuk {days} hari ke belakang...")
        
        # Iterasi mundur
        for i in range(1, days + 1):
            target = today - timedelta(days=i)
            # Lewati Sabtu dan Minggu secara default agar hemat request
            if target.weekday() >= 5:
                continue
                
            date_str = target.strftime('%Y%M%d')
            # Wait, the parameter in IDX API usually uses YYYYMMDD
            # Let's fix the strftime
            date_str_correct = target.strftime('%Y%m%d')
            fetch_daily_data_idx_by_date(db, date_str_correct)
            sleep(1) # Jeda agar tidak diblokir
            
        print("Selesai mengambil data historis harian!")
    finally:
        db.close()

if __name__ == "__main__":
    days_to_fetch = 15 # Ambil 15 hari kalender ke belakang (akan memotong weekend, jadi sekitar 10 hari bursa)
    if len(sys.argv) > 1:
        try:
            days_to_fetch = int(sys.argv[1])
        except ValueError:
            pass
    fetch_past_days(days_to_fetch)
