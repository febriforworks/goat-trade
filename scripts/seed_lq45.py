import os
import sys
import datetime
from sqlalchemy.orm import Session

# Tambahkan path aplikasi agar bisa import module dari app/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal
from app.db.models import IndexMembership, Company

def seed_lq45():
    db = SessionLocal()
    try:
        # Daftar LQ45 periode terbaru (Contoh: Nov 2024 - Jan 2025)
        # Sesuai dengan evaluasi mayor BEI terbaru
        lq45_tickers = [
            "ACES", "ADMR", "ADRO", "AKRA", "AMMN", "AMRT", "ANTM", "ARTO", "ASII", 
            "BBCA", "BBNI", "BBRI", "BBTN", "BMRI", "BRIS", "BRPT", "BUKA", "CPIN", 
            "ESSA", "EXCL", "GOTO", "ICBP", "INCO", "INDF", "INKP", "INTP", "ISAT", 
            "ITMG", "JSMR", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "MTEL", "PGAS", 
            "PGEO", "PTBA", "SIDO", "SMGR", "SMRA", "TLKM", "TOWR", "UNTR", "UNVR"
        ]

        # Validasi apakah ticker ada di tabel Company
        existing_companies = {c.code for c in db.query(Company.code).all()}
        valid_tickers = [t for t in lq45_tickers if t in existing_companies]
        
        print(f"Ditemukan {len(valid_tickers)} saham dari 45 saham LQ45 di database.")

        # Hapus data keanggotaan LQ45 yang lama agar tidak tumpang tindih
        deleted = db.query(IndexMembership).filter(IndexMembership.index_code == "LQ45").delete()
        print(f"Menghapus {deleted} record LQ45 lama...")

        # Tambahkan data baru
        start_date = datetime.date(2024, 11, 1) # Tanggal efektif evaluasi
        records = []
        for ticker in valid_tickers:
            records.append(IndexMembership(
                index_code="LQ45",
                company_code=ticker,
                start_date=start_date,
                end_date=None # None = Aktif sampai sekarang
            ))

        db.bulk_save_objects(records)
        db.commit()
        print(f"Berhasil menyimpan {len(records)} saham LQ45 ke database.")

    except Exception as e:
        print(f"Terjadi kesalahan: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_lq45()
