import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db.database import SessionLocal
from app.db.models import Company, HistoricalPrice, DailyMarketData, CorporateAction, IndexMembership, StockStatus, ScreenerResult

def clean_empty_companies():
    db = SessionLocal()
    try:
        companies = db.query(Company).all()
        to_delete = []
        
        for comp in companies:
            hist_count = db.query(HistoricalPrice).filter_by(company_code=comp.code).count()
            daily_count = db.query(DailyMarketData).filter_by(company_code=comp.code).count()
            
            if hist_count == 0 and daily_count == 0:
                to_delete.append(comp.code)
                
        print(f"Ditemukan {len(to_delete)} emiten yang sama sekali tidak memiliki data transaksi.")
        
        if to_delete:
            print("Menghapus data terkait (jika ada)...")
            db.query(CorporateAction).filter(CorporateAction.company_code.in_(to_delete)).delete(synchronize_session=False)
            db.query(IndexMembership).filter(IndexMembership.company_code.in_(to_delete)).delete(synchronize_session=False)
            db.query(StockStatus).filter(StockStatus.company_code.in_(to_delete)).delete(synchronize_session=False)
            db.query(ScreenerResult).filter(ScreenerResult.company_code.in_(to_delete)).delete(synchronize_session=False)
            
            print("Menghapus emiten dari tabel utama...")
            db.query(Company).filter(Company.code.in_(to_delete)).delete(synchronize_session=False)
            
            db.commit()
            print(f"Berhasil menghapus {len(to_delete)} emiten dari database.")
            print("List emiten yang dihapus:", ", ".join(to_delete))
        else:
            print("Tidak ada emiten kosong yang perlu dihapus.")
            
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clean_empty_companies()
