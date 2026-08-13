import os
import sys
import time
import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy import func
import numpy as np

# Tambahkan path aplikasi
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal
from app.db.models import Company, HistoricalPrice

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def fetch_history_batch():
    db = SessionLocal()
    try:
        # 1. Ambil semua kode emiten yang ada di DB
        companies = db.query(Company.code).all()
        tickers = [c.code for c in companies]
        
        # 2. Cari tanggal terlama yang ada di database saat ini
        min_date_record = db.query(func.min(HistoricalPrice.date)).first()
        min_date_db = min_date_record[0] if min_date_record and min_date_record[0] else None
        
        if not min_date_db:
            print("Belum ada data di historical_prices. Akan menarik dari 3 tahun lalu.")
            end_date = pd.Timestamp.today().strftime('%Y-%m-%d')
        else:
            # Karena sudah ada dari min_date_db, kita tarik s.d. H-1 dari tanggal tersebut
            end_date_dt = pd.to_datetime(min_date_db) - pd.Timedelta(days=1)
            end_date = end_date_dt.strftime('%Y-%m-%d')
            
        # Target awal: 3 tahun ke belakang (misal dari 2023-01-01)
        start_date = "2023-01-01"
        
        # Validasi jika data di DB sudah lebih tua dari target start_date
        if min_date_db and pd.to_datetime(min_date_db) <= pd.to_datetime(start_date):
            print(f"Data di database sudah mencakup {start_date}. Tidak perlu ditarik lagi.")
            return

        print(f"Menarik data dari {start_date} hingga {end_date} untuk {len(tickers)} emiten...")
        print("Metode: Batching 50 ticker per request (menjaga IP aman dari rate limit yfinance)...")
        
        chunk_size = 50
        total_saved = 0
        
        for i, chunk in enumerate(chunk_list(tickers, chunk_size)):
            print(f"\nMemproses batch {i+1} / {(len(tickers)//chunk_size)+1} ...")
            yf_tickers = [f"{t}.JK" for t in chunk]
            
            try:
                # Menarik banyak ticker sekaligus jauh lebih cepat dan ramah server
                data = yf.download(yf_tickers, start=start_date, end=end_date, group_by='ticker', threads=True, progress=False)
                
                if data.empty:
                    print("Data kosong dari Yahoo Finance untuk batch ini.")
                    continue
                    
                records = []
                
                if len(yf_tickers) == 1:
                    # Jika hanya 1 ticker, pandas dataframe strukturnya normal
                    df = data.dropna(subset=['Close']).replace({np.nan: None})
                    t = chunk[0]
                    for date, row in df.iterrows():
                        records.append(HistoricalPrice(
                            company_code=t,
                            date=date.date(),
                            open_price=float(row.get('Open')) if row.get('Open') is not None else None,
                            high=float(row.get('High')) if row.get('High') is not None else None,
                            low=float(row.get('Low')) if row.get('Low') is not None else None,
                            close=float(row.get('Close')) if row.get('Close') is not None else None,
                            volume=int(row.get('Volume')) if row.get('Volume') is not None else None
                        ))
                else:
                    # Jika banyak ticker, strukturnya MultiIndex
                    for t in chunk:
                        yf_t = f"{t}.JK"
                        if yf_t not in data.columns.levels[0]:
                            continue
                            
                        # Ambil data spesifik per ticker
                        df = data[yf_t].dropna(subset=['Close']).replace({np.nan: None})
                        for date, row in df.iterrows():
                            records.append(HistoricalPrice(
                                company_code=t,
                                date=date.date(),
                                open_price=float(row.get('Open')) if row.get('Open') is not None else None,
                                high=float(row.get('High')) if row.get('High') is not None else None,
                                low=float(row.get('Low')) if row.get('Low') is not None else None,
                                close=float(row.get('Close')) if row.get('Close') is not None else None,
                                volume=int(row.get('Volume')) if row.get('Volume') is not None else None
                            ))
                            
                if records:
                    db.bulk_save_objects(records)
                    db.commit()
                    total_saved += len(records)
                    print(f" -> Berhasil menyimpan {len(records)} baris sejarah harga.")
                else:
                    print(" -> Tidak ada data valid yang bisa disimpan.")
                    
            except Exception as e:
                print(f"Error di batch {i+1}: {e}")
                db.rollback()
                
            # Jeda 2 detik antar batch agar IP tidak diblokir Yahoo
            time.sleep(2) 
            
        print(f"\nSelesai! Total baris data yang ditambahkan: {total_saved}")

    except Exception as e:
        print(f"Terjadi kesalahan fatal: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fetch_history_batch()
