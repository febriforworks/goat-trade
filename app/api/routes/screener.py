from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Company
from app.services.screener import ScreenerConfig, run_screener
from app.services.notifier import ws_manager, send_telegram_alert, format_telegram_message
from datetime import datetime
import numpy as np

router = APIRouter()

@router.get("/run", summary="Execute Screener")
@router.post("/run", include_in_schema=False)
async def execute_screener(db: Session = Depends(get_db)):
    """
    Menjalankan proses screener untuk seluruh emiten.
    - Otomatis skip jika akhir pekan (Sabtu/Minggu)
    - Menghitung indikator teknikal (MA, ADX, Breakout, Volume)
    - Memeriksa akumulasi asing
    - Menyimpan hasil ke database
    - Mengirim notifikasi WebSocket dan Telegram jika ada kandidat kuat
    """
    # 0. Cek Akhir Pekan
    today = datetime.now()
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
