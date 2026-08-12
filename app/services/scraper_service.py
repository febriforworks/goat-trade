import pandas as pd
import yfinance as yf
import cloudscraper
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

def fetch_daily_data_idx(db: Session):
    http = cloudscraper.CloudScraper()
    link = "https://idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0"
    
    try:
        response = http.get(link)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text}")
        result = json.loads(response.text)
    except Exception as e:
        print(f"Error fetching bulk daily data: {e}")
        return {"message": "Gagal menarik data dari IDX."}
        
    data_list = result.get("data", [])
    if not data_list:
        return {"message": "Data kosong dari IDX."}
        
    records_to_insert = []
    total_saved = 0
    
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
        total_saved += len(records_to_insert)

    return {"message": f"Successfully saved {total_saved} daily market data records."}
