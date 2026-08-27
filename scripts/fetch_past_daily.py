import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from time import sleep

from app.db.database import SessionLocal, init_db
from app.db.models import Company, DailyMarketData
from app.core.timezone import get_jakarta_now
from app.services.scraper_service import create_idx_scraper

def to_int(val):
    if val is None or pd.isna(val):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

def to_float(val):
    if val is None or pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def fetch_daily_data_idx_by_date(db: Session, target_date: str, http_session=None):
    """
    Fetch IDX summary for a specific date.
    target_date format: YYYYMMDD
    """
    # 0. Cek terlebih dahulu apakah data tanggal ini sudah lengkap di DB (opsional hemat request)
    try:
        parsed_target = datetime.strptime(target_date, "%Y%m%d").date()
        count_existing = db.query(DailyMarketData.id).filter(DailyMarketData.date == parsed_target).count()
        if count_existing > 500:
            print(f"[{target_date}] INFO: Data tanggal {parsed_target} sudah ada di database ({count_existing} records). Melewati request ke IDX.")
            return
    except Exception:
        pass

    browsers = ["chrome120", "chrome124", "safari17_0"]
    http = http_session or create_idx_scraper(browsers[0])
    link = f"https://idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0&date={target_date}"
    
    print(f"[{target_date}] Mengirim request ke IDX API: {link}")
    result = None
    for attempt in range(1, 4):
        browser_choice = browsers[(attempt - 1) % len(browsers)]
        if attempt > 1:
            http = create_idx_scraper(impersonate_browser=browser_choice)
        try:
            response = http.get(link, timeout=25)
            if response.status_code == 200:
                try:
                    result = json.loads(response.text)
                    break
                except Exception:
                    print(f"[{target_date}] (Percobaan {attempt}/3 - {browser_choice}) Respons bukan format JSON valid.")
            else:
                print(f"[{target_date}] (Percobaan {attempt}/3 - {browser_choice}) Gagal HTTP {response.status_code}: {response.text[:150]}")
        except Exception as e:
            print(f"[{target_date}] (Percobaan {attempt}/3 - {browser_choice}) Error fetching data dari IDX: {e}")
        
        if attempt < 3:
            sleep(3 * attempt)

    if result is None:
        print(f"[{target_date}] Gagal mengambil data setelah 3 percobaan.")
        return
        
    data_list = result.get("data", [])
    if not data_list:
        print(f"[{target_date}] Data kosong dari IDX (mungkin hari libur bursa / belum tutup bursa).")
        return
        
    print(f"[{target_date}] Menerima {len(data_list)} baris data dari IDX.")

    # 1. Pastikan seluruh emiten terdaftar di tabel companies
    existing_companies = {c.code for c in db.query(Company.code).all()}
    new_companies = []
    
    for data in data_list:
        code = data.get("StockCode")
        if not code or code in existing_companies:
            continue
        company_name = data.get("StockName") or code
        listed_shares = to_int(data.get("ListedShares"))
        new_comp = Company(
            code=code,
            name=company_name,
            shares=listed_shares
        )
        db.add(new_comp)
        existing_companies.add(code)
        new_companies.append(new_comp)

    if new_companies:
        db.commit()
        print(f"[{target_date}] Berhasil mendaftarkan {len(new_companies)} emiten baru ke tabel 'companies'.")

    # 2. Parse tanggal perdagangan dari row pertama
    first_row_date = data_list[0].get('Date')
    try:
        trade_date = datetime.strptime(first_row_date, '%Y-%m-%dT%H:%M:%S').date()
    except Exception:
        trade_date = pd.to_datetime(first_row_date).date()

    print(f"[{target_date}] Tanggal perdagangan bursa: {trade_date}")

    # 3. Ambil data yang sudah ada untuk tanggal tersebut (1 single SQL query)
    existing_daily_codes = {
        r[0] for r in db.query(DailyMarketData.company_code).filter(DailyMarketData.date == trade_date).all()
    }

    records_to_insert = []
    
    for data in data_list:
        code = data.get("StockCode")
        if not code or code in existing_daily_codes:
            continue
        
        # Validasi row date jika berbeda
        row_date_str = data.get('Date')
        try:
            row_date = datetime.strptime(row_date_str, '%Y-%m-%dT%H:%M:%S').date()
        except Exception:
            row_date = pd.to_datetime(row_date_str).date()
            
        record = DailyMarketData(
            company_code=code,
            date=row_date,
            previous=to_float(data.get('Previous')),
            open_price=to_float(data.get('OpenPrice')),
            first_trade=to_float(data.get('FirstTrade')),
            high=to_float(data.get('High')),
            low=to_float(data.get('Low')),
            close=to_float(data.get('Close')),
            change=to_float(data.get('Change')),
            volume=to_int(data.get('Volume')),
            value=to_float(data.get('Value')),
            frequency=to_int(data.get('Frequency')),
            index_individual=to_float(data.get('IndexIndividual')),
            offer=to_float(data.get('Offer')),
            offer_volume=to_int(data.get('OfferVolume')),
            bid=to_float(data.get('Bid')),
            bid_volume=to_int(data.get('BidVolume')),
            listed_shares=to_int(data.get('ListedShares')),
            tradeble_shares=to_int(data.get('TradebleShares')),
            weight_for_index=to_float(data.get('WeightForIndex')),
            foreign_sell=to_int(data.get('ForeignSell')),
            foreign_buy=to_int(data.get('ForeignBuy')),
            delisting_date=pd.to_datetime(data['DelistingDate']).date() if data.get('DelistingDate') else None,
            non_regular_volume=to_int(data.get('NonRegularVolume')),
            non_regular_value=to_float(data.get('NonRegularValue')),
            non_regular_frequency=to_int(data.get('NonRegularFrequency'))
        )
        records_to_insert.append(record)
        existing_daily_codes.add(code)
        
    if records_to_insert:
        db.bulk_save_objects(records_to_insert)
        db.commit()
        print(f"[{target_date}] SUKSES: Berhasil menyimpan {len(records_to_insert)} records ke tabel 'daily_market_data'.")
    else:
        print(f"[{target_date}] INFO: 0 records baru untuk dimasukkan (data tanggal {trade_date} sudah lengkap di database).")

def fetch_past_days(days=10):
    init_db()
    db = SessionLocal()
    try:
        http = create_idx_scraper()
        today = get_jakarta_now()
        print(f"Mulai mengambil data historis harian IDX untuk {days} hari ke belakang (WIB)...")
        
        for i in range(1, days + 1):
            target = today - timedelta(days=i)
            # Lewati Sabtu dan Minggu
            if target.weekday() >= 5:
                continue
                
            date_str = target.strftime('%Y%m%d')
            fetch_daily_data_idx_by_date(db, date_str, http_session=http)
            sleep(2) # Jeda agar tidak terkena rate-limit / Cloudflare WAF
            
        print("Selesai mengambil data historis harian!")
    finally:
        try:
            db.close()
        except Exception:
            pass

if __name__ == "__main__":
    days_to_fetch = 15
    if len(sys.argv) > 1:
        try:
            days_to_fetch = int(sys.argv[1])
        except ValueError:
            pass
    fetch_past_days(days_to_fetch)
