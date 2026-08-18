from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.db.database import get_db
from app.db.models import Company, ScreenerResult
from app.services.screener import ScreenerConfig, run_screener
from app.services.notifier import ws_manager, send_telegram_alert, format_telegram_message
from app.core.timezone import get_jakarta_now
from typing import Optional
from datetime import date
import numpy as np

router = APIRouter()

@router.get("/latest", summary="Get Latest Screener Results")
def get_latest_screener_results(
    db: Session = Depends(get_db),
    min_score: int = Query(default=0, description="Minimal skor screener"),
    only_breakout: bool = Query(default=False, description="Hanya tampilkan yang breakout_ok=True"),
    limit: int = Query(default=100, le=500, description="Maksimal data yang dikembalikan")
):
    """
    Mengambil hasil screener terbaru yang sudah tersimpan di database.
    Sangat cepat (<50ms), ringan, dan aman dipanggil dari Vercel / Frontend tanpa batas timeout.
    """
    latest_date = db.query(func.max(ScreenerResult.date)).scalar()
    if not latest_date:
        return {
            "status": "ok",
            "message": "Belum ada hasil screener di database. Jalankan pipeline GitHub Actions terlebih dahulu.",
            "date": None,
            "total": 0,
            "data": []
        }
        
    query = db.query(ScreenerResult, Company.name, Company.listing_board)\
        .outerjoin(Company, ScreenerResult.company_code == Company.code)\
        .filter(ScreenerResult.date == latest_date)
        
    if min_score > 0:
        query = query.filter(ScreenerResult.score >= min_score)
    if only_breakout:
        query = query.filter(ScreenerResult.breakout_ok == True)
        
    results = query.order_by(desc(ScreenerResult.score)).limit(limit).all()
    
    data = []
    for sr, name, board in results:
        data.append({
            "ticker": sr.company_code,
            "name": name,
            "board": board,
            "date": str(sr.date),
            "score": sr.score,
            "trend_ok": sr.trend_ok,
            "breakout_ok": sr.breakout_ok,
            "volume_ok": sr.volume_ok,
            "foreign_ok": sr.foreign_ok,
            "close": float(sr.close_price) if sr.close_price is not None else None,
            "stop_loss": float(sr.stop_loss) if sr.stop_loss is not None else None,
            "risk_pct": float(sr.risk_pct) if sr.risk_pct is not None else None,
            "atr": float(sr.atr) if sr.atr is not None else None,
            "transaction_value": float(sr.transaction_value) if sr.transaction_value is not None else None
        })
        
    return {
        "status": "ok",
        "date": str(latest_date),
        "total": len(data),
        "data": data
    }


@router.get("/history", summary="Get Historical Screener Results")
def get_screener_history(
    target_date: Optional[str] = Query(default=None, description="Tanggal format YYYY-MM-DD"),
    db: Session = Depends(get_db),
    min_score: int = Query(default=0),
    limit: int = Query(default=100, le=500)
):
    """Mengambil hasil screener untuk tanggal historis tertentu."""
    if not target_date:
        return get_latest_screener_results(db=db, min_score=min_score, limit=limit)
        
    try:
        parsed_date = date.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal tidak valid. Gunakan YYYY-MM-DD")
        
    query = db.query(ScreenerResult, Company.name, Company.listing_board)\
        .outerjoin(Company, ScreenerResult.company_code == Company.code)\
        .filter(ScreenerResult.date == parsed_date)
        
    if min_score > 0:
        query = query.filter(ScreenerResult.score >= min_score)
        
    results = query.order_by(desc(ScreenerResult.score)).limit(limit).all()
    
    data = []
    for sr, name, board in results:
        data.append({
            "ticker": sr.company_code,
            "name": name,
            "board": board,
            "date": str(sr.date),
            "score": sr.score,
            "trend_ok": sr.trend_ok,
            "breakout_ok": sr.breakout_ok,
            "volume_ok": sr.volume_ok,
            "foreign_ok": sr.foreign_ok,
            "close": float(sr.close_price) if sr.close_price is not None else None,
            "stop_loss": float(sr.stop_loss) if sr.stop_loss is not None else None,
            "risk_pct": float(sr.risk_pct) if sr.risk_pct is not None else None,
            "atr": float(sr.atr) if sr.atr is not None else None,
            "transaction_value": float(sr.transaction_value) if sr.transaction_value is not None else None
        })
        
    return {
        "status": "ok",
        "date": str(parsed_date),
        "total": len(data),
        "data": data
    }


@router.get("/run", summary="Execute Screener (Calculation Engine)")
@router.post("/run", include_in_schema=False)
async def execute_screener(db: Session = Depends(get_db)):
    """
    Menjalankan proses screener untuk seluruh emiten.
    Catatan: Di serverless Vercel, disarankan menggunakan GitHub Actions agar tidak terkena timeout 10 detik.
    """
    # 0. Cek Akhir Pekan (WIB)
    today = get_jakarta_now()
    if today.weekday() >= 5:
        return {
            "status": "ok",
            "message": "Hari ini adalah akhir pekan (Sabtu/Minggu). Bursa tutup, screener otomatis dilewati.",
            "total_screened": 0,
            "total_kandidat": 0,
            "data": []
        }

    cfg = ScreenerConfig()
    
    # 1. Fetch companies
    companies = db.query(Company).all()
    watchlist = [c.code for c in companies]
    
    # 2. Run screener
    hasil = run_screener(db, watchlist, cfg, save_to_db=True)
    
    if hasil.empty:
        return {"status": "ok", "message": "Screener selesai, tidak ada data."}
        
    # 3. Filter kandidat kuat (Wajib lolos Hard Gates dan terjadi Breakout)
    kandidat_kuat = hasil[(hasil["trend_ok"] == True) & (hasil["breakout_ok"] == True)]
    
    # 4. Format for JSON (handle date and NaN)
    kandidat_kuat_str = kandidat_kuat.copy()
    kandidat_kuat_str['date'] = kandidat_kuat_str['date'].astype(str)
    alerts_payload = kandidat_kuat_str.replace({np.nan: None}).to_dict(orient="records")
    
    # 5. Broadcast alerts if any
    if alerts_payload:
        ws_payload = {
            "type": "screener_signals",
            "data": alerts_payload
        }
        await ws_manager.broadcast_json(ws_payload)
        
        telegram_msg = format_telegram_message(alerts_payload)
        send_telegram_alert(telegram_msg)
        
    return {
        "status": "ok", 
        "message": "Screener berhasil dieksekusi",
        "total_screened": len(watchlist),
        "total_kandidat": len(alerts_payload),
        "data": alerts_payload
    }
