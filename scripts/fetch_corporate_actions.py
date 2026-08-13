import os
import sys
import time
import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db.database import SessionLocal
from app.db.models import Company, CorporateAction, CorporateActionType

def fetch_corporate_actions():
    db = SessionLocal()
    try:
        # Get all companies
        companies = db.query(Company.code).all()
        tickers = [c.code for c in companies]
        
        print(f"Menarik data aksi korporasi untuk {len(tickers)} emiten...")
        
        total_actions_saved = 0
        
        for i, t in enumerate(tickers):
            if i % 50 == 0 and i > 0:
                print(f"Memproses {i}/{len(tickers)} emiten... (istirahat 2 detik)")
                time.sleep(2)
                
            yf_ticker = f"{t}.JK"
            
            try:
                stock = yf.Ticker(yf_ticker)
                actions = stock.actions
                
                if actions is None or actions.empty:
                    continue
                    
                records = []
                for date, row in actions.iterrows():
                    # Check Dividends
                    div = row.get("Dividends", 0)
                    if div > 0:
                        records.append({
                            "company_code": t,
                            "ex_date": date.date(),
                            "action_type": CorporateActionType.DIVIDEND,
                            "value": float(div),
                            "ratio": None
                        })
                        
                    # Check Splits
                    split = row.get("Stock Splits", 0)
                    if split > 0:
                        records.append({
                            "company_code": t,
                            "ex_date": date.date(),
                            "action_type": CorporateActionType.SPLIT,
                            "value": None,
                            "ratio": float(split)
                        })
                
                if records:
                    # Gunakan UPSERT untuk mengabaikan duplikat jika dijalankan berulang
                    stmt = insert(CorporateAction).values(records)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=['company_code', 'ex_date', 'action_type']
                    )
                    db.execute(stmt)
                    db.commit()
                    total_actions_saved += len(records)
                    
            except Exception as e:
                # print(f"Error memproses {t}: {e}")
                db.rollback()
                pass
                
        print(f"\nSelesai! Berhasil menyimpan {total_actions_saved} aksi korporasi (Dividen & Split).")
        
    except Exception as e:
        print(f"Fatal Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fetch_corporate_actions()
