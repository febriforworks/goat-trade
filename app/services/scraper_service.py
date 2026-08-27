import pandas as pd
import yfinance as yf
import cloudscraper
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
import json
from time import sleep
from sqlalchemy.orm import Session
from datetime import datetime

from app.db.models import Company, HistoricalPrice, DailyMarketData

def sync_companies_from_excel(db: Session, excel_path: str = 'list-saham-20260809.xlsx'):
    try:
        df_all = pd.read_excel(excel_path)
    except FileNotFoundError:
        raise Exception(f"File {excel_path} not found.")

    lq45_codes = set()
    count = 0
    for index, row in df_all.iterrows():
        code = str(row['Kode']).strip()
        
        company = db.query(Company).filter(Company.code == code).first()
        if not company:
            company = Company(code=code)
            db.add(company)
        
        company.name = row['Nama Perusahaan']
        
        listing_date = pd.to_datetime(row['Tanggal Pencatatan'], errors='coerce')
        company.listing_date = listing_date.date() if pd.notnull(listing_date) else None
        
        shares_str = str(row['Saham']).replace('.', '')
        try:
            company.shares = int(shares_str)
        except ValueError:
            company.shares = None
            
        company.listing_board = row['Papan Pencatatan'] if pd.notnull(row['Papan Pencatatan']) else None
        company.is_lq45 = (code in lq45_codes)
        count += 1

    db.commit()
    return {"message": f"Successfully synced {count} companies."}

def fetch_historical_data_yfinance(db: Session):
    companies = db.query(Company).all()
    if not companies:
        raise Exception("Database is empty. Sync companies first.")

    total_saved = 0
    for company in companies:
        code = company.code
        ticker_symbol = f"{code}.JK"
        
        try:
            ticker = yf.Ticker(ticker_symbol)
            history = ticker.history(period="1y")
        except Exception as e:
            print(f"Error fetching {code}: {e}")
            continue
        
        if history.empty:
            continue
            
        history = history.reset_index()
        records_to_insert = []
        
        for index, row in history.iterrows():
            # In yfinance, the Date is usually timezone-aware, so we convert it
            trade_date = row['Date'].date() if hasattr(row['Date'], 'date') else row['Date']
            
            exists = db.query(HistoricalPrice).filter(
                HistoricalPrice.company_code == code,
                HistoricalPrice.date == trade_date
            ).first()
            
            if not exists:
                prev_close = history.loc[index - 1, 'Close'] if index > 0 else None
                change = row['Close'] - prev_close if prev_close else None
                
                # Konversi tipe numpy ke python native agar psycopg2 tidak error
                record = HistoricalPrice(
                    company_code=code,
                    date=trade_date,
                    previous=float(prev_close) if pd.notna(prev_close) else None,
                    open_price=float(row['Open']) if pd.notna(row['Open']) else None,
                    high=float(row['High']) if pd.notna(row['High']) else None,
                    low=float(row['Low']) if pd.notna(row['Low']) else None,
                    close=float(row['Close']) if pd.notna(row['Close']) else None,
                    change=float(change) if pd.notna(change) else None,
                    volume=int(row['Volume']) if pd.notna(row['Volume']) else None
                )
                records_to_insert.append(record)
        
        if records_to_insert:
            db.bulk_save_objects(records_to_insert)
            db.commit()
            total_saved += len(records_to_insert)
            
        sleep(0.5)

    return {"message": f"Successfully saved {total_saved} historical price records."}

def create_idx_scraper(impersonate_browser: str = "chrome120"):
    if HAS_CURL_CFFI:
        scraper = cffi_requests.Session(impersonate=impersonate_browser)
        scraper.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://idx.co.id/',
        })
        return scraper

    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    scraper.headers.update({
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://idx.co.id/',
    })
    return scraper

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

def fetch_daily_data_idx(db: Session):
    browsers = ["chrome120", "chrome124", "safari17_0"]
    http = create_idx_scraper(browsers[0])
    link = "https://idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0"
    
    result = None
    last_error = None
    for attempt in range(1, 4):
        browser_choice = browsers[(attempt - 1) % len(browsers)]
        if attempt > 1:
            http = create_idx_scraper(impersonate_browser=browser_choice)
        try:
            response = http.get(link, timeout=25)
            if response.status_code == 200:
                result = json.loads(response.text)
                break
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"[Daily] (Percobaan {attempt}/3 - {browser_choice}) {last_error}")
        except Exception as e:
            last_error = str(e)
            print(f"[Daily] (Percobaan {attempt}/3 - {browser_choice}) Error fetching data: {e}")
        
        if attempt < 3:
            sleep(2 * attempt)

    if result is None:
        print(f"Error fetching bulk daily data: {last_error}")
        return {"status": "error", "message": f"Gagal menarik data dari IDX: {last_error}"}
        
    data_list = result.get("data", [])
    if not data_list:
        return {"status": "ok", "message": "Data kosong dari IDX."}
        
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

    first_row_date = data_list[0].get('Date')
    try:
        trade_date = datetime.strptime(first_row_date, '%Y-%m-%dT%H:%M:%S').date()
    except Exception:
        trade_date = pd.to_datetime(first_row_date).date()

    existing_daily_codes = {
        r[0] for r in db.query(DailyMarketData.company_code).filter(DailyMarketData.date == trade_date).all()
    }

    records_to_insert = []
    for data in data_list:
        code = data.get("StockCode")
        if not code or code in existing_daily_codes: 
            continue
        
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

    return {"status": "ok", "message": f"Successfully saved {len(records_to_insert)} daily market data records (tanggal: {trade_date})."}
