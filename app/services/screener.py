"""
IDX Swing Trading Screener - Kerangka Dasar
=============================================
Kerangka screening saham IDX untuk swing trading berbasis:
  1. Trend filter       (Moving Average + ADX)
  2. Breakout trigger    (Donchian Channel breakout)
  3. Volume confirmation (volume relatif terhadap rata-rata)
  4. Foreign flow        (opsional, dari data Ringkasan Perdagangan IDX)

Dependency:
    pip install yfinance pandas numpy

Catatan penting:
- Ini kerangka teknis, BUKAN rekomendasi saham atau jaminan profit.
  Backtest dulu tiap kriteria sebelum dipakai untuk keputusan nyata.
- Data foreign flow TIDAK diambil dari yfinance (seringkali kosong untuk
  saham IDX). Kerangka ini mengasumsikan kamu punya pipeline terpisah yang
  mengunduh & memparse file "Ringkasan Saham" / "Ringkasan Broker" dari
  idx.co.id (Data Pasar > Ringkasan Perdagangan) menjadi CSV per ticker
  dengan kolom minimal: Date, ForeignBuy, ForeignSell.
  Lihat fungsi `load_foreign_flow()` di bawah — sesuaikan dengan format
  file yang kamu hasilkan dari pipeline itu.
"""

import os
import requests
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.db.models import HistoricalPrice, DailyMarketData, Company, CorporateAction, CorporateActionType, StockStatus, ScreenerResult


# ============================================================
# 1. KONFIGURASI
# ============================================================

@dataclass
class ScreenerConfig:
    ma_short: int = 20
    ma_long_trend: int = 50
    ma_long_confirm: int = 200
    adx_period: int = 14
    adx_threshold: float = 15.0
    breakout_lookback: int = 20
    volume_avg_period: int = 20
    volume_multiplier: float = 1.35
    foreign_flow_days: int = 5
    min_foreign_buy_days: int = 3  # minimal hari net buy dalam window di atas
    min_transaction_value: int = 2_000_000_000
    min_trading_days: int = 15
    max_risk_pct: float = 0.08
    breakout_recency_days: int = 3
    max_extension_from_ma50: float = 0.15
    candle_close_threshold: float = 0.60


# ============================================================
# 2. DATA LOADING
# ============================================================

def load_data_from_db(db: Session, ticker_code: str) -> pd.DataFrame:
    """
    Ambil data OHLCV dan Foreign Flow dari database (tabel HistoricalPrice dan DailyMarketData).
    Gabungkan hasilnya agar data histori panjang dan foreign flow harian menyatu.
    """
    # 1. Query histori
    hist_query = db.query(
        HistoricalPrice.date, 
        HistoricalPrice.open_price, 
        HistoricalPrice.high, 
        HistoricalPrice.low, 
        HistoricalPrice.close, 
        HistoricalPrice.volume
    ).filter(HistoricalPrice.company_code == ticker_code)
    
    hist_df = pd.read_sql(hist_query.statement, db.bind)
    
    # 2. Query daily
    daily_query = db.query(
        DailyMarketData.date,
        DailyMarketData.open_price,
        DailyMarketData.high,
        DailyMarketData.low,
        DailyMarketData.close,
        DailyMarketData.volume,
        DailyMarketData.foreign_buy,
        DailyMarketData.foreign_sell
    ).filter(DailyMarketData.company_code == ticker_code)
    
    daily_df = pd.read_sql(daily_query.statement, db.bind)
    
    if hist_df.empty and daily_df.empty:
        raise ValueError(f"Data kosong untuk {ticker_code}")
        
    # Formatting hist_df
    if not hist_df.empty:
        hist_df['date'] = pd.to_datetime(hist_df['date'])
        hist_df = hist_df.set_index('date')
        hist_df.rename(columns={'open_price': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        # ubah tipe kolom
        hist_df = hist_df.astype({'Open': float, 'High': float, 'Low': float, 'Close': float, 'Volume': float})
        
    # Formatting daily_df
    if not daily_df.empty:
        daily_df['date'] = pd.to_datetime(daily_df['date'])
        daily_df = daily_df.set_index('date')
        daily_df['foreign_buy'] = daily_df['foreign_buy'].fillna(0).astype(float)
        daily_df['foreign_sell'] = daily_df['foreign_sell'].fillna(0).astype(float)
        daily_df['NetForeign'] = daily_df['foreign_buy'] - daily_df['foreign_sell']
        
        daily_df.rename(columns={'open_price': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        daily_df = daily_df[['Open', 'High', 'Low', 'Close', 'Volume', 'NetForeign']]
        daily_df = daily_df.astype({'Open': float, 'High': float, 'Low': float, 'Close': float, 'Volume': float})
    else:
        daily_df = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume', 'NetForeign'])
        
    # Merge
    if not hist_df.empty and not daily_df.empty:
        combined = daily_df.combine_first(hist_df)
    elif not hist_df.empty:
        combined = hist_df
    else:
        combined = daily_df
        
    if 'NetForeign' not in combined.columns:
        combined['NetForeign'] = 0.0
        
    # Pastikan data float untuk mencegah masalah saat kalkulasi
    combined['NetForeign'] = combined['NetForeign'].fillna(0.0)
    combined.sort_index(inplace=True)
    
    # Adjust for corporate actions
    combined = apply_corporate_actions(combined, db, ticker_code)
    
    # 3. Query StockStatus
    status_query = db.query(
        StockStatus.date,
        StockStatus.is_suspended,
        StockStatus.ara_limit,
        StockStatus.arb_limit
    ).filter(StockStatus.company_code == ticker_code)
    
    status_df = pd.read_sql(status_query.statement, db.bind)
    
    if not status_df.empty:
        status_df['date'] = pd.to_datetime(status_df['date'])
        status_df = status_df.set_index('date')
        combined = combined.join(status_df, how='left')
    
    # Fill missing status values with False/None as appropriate
    if 'is_suspended' not in combined.columns:
        combined['is_suspended'] = False
        combined['ara_limit'] = pd.NA
        combined['arb_limit'] = pd.NA
    else:
        combined['is_suspended'] = combined['is_suspended'].fillna(False).astype(bool)
    
    return combined

def apply_corporate_actions(df: pd.DataFrame, db: Session, ticker_code: str) -> pd.DataFrame:
    """
    Adjust historical prices (O,H,L,C,V) for corporate actions (splits/reverse splits).
    """
    if df.empty:
        return df
        
    actions = db.query(CorporateAction).filter(
        CorporateAction.company_code == ticker_code,
        CorporateAction.action_type.in_([CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT])
    ).order_by(CorporateAction.ex_date.desc()).all()
    
    if not actions:
        return df
        
    df_adj = df.copy()
    
    for action in actions:
        ex_date = pd.to_datetime(action.ex_date)
        # Apply to all dates strictly BEFORE the ex_date
        mask = df_adj.index < ex_date
        ratio = float(action.ratio) if action.ratio else 1.0
        
        if action.action_type == CorporateActionType.SPLIT:
            # 1:5 split (ratio=5) -> divide prices by 5, multiply volume by 5
            multiplier = 1 / ratio
            vol_multiplier = ratio
        elif action.action_type == CorporateActionType.REVERSE_SPLIT:
            # 5:1 split (ratio=5) -> multiply prices by 5, divide volume by 5
            multiplier = ratio
            vol_multiplier = 1 / ratio
        else:
            continue
            
        df_adj.loc[mask, 'Open'] *= multiplier
        df_adj.loc[mask, 'High'] *= multiplier
        df_adj.loc[mask, 'Low'] *= multiplier
        df_adj.loc[mask, 'Close'] *= multiplier
        df_adj.loc[mask, 'Volume'] *= vol_multiplier
        
    return df_adj


# ============================================================
# 3. INDIKATOR
# ============================================================

def add_moving_averages(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    df = df.copy()
    df["MA_short"] = df["Close"].rolling(cfg.ma_short).mean()
    df["MA_trend"] = df["Close"].rolling(cfg.ma_long_trend).mean()
    df["MA_confirm"] = df["Close"].rolling(cfg.ma_long_confirm).mean()
    return df


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    ADX (Average Directional Index) versi manual, tanpa dependency tambahan
    (mis. TA-Lib), supaya kerangka ini tetap ringan untuk diadaptasi.
    """
    df = df.copy()
    high, low, close = df["High"], df["Low"], df["Close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr)

    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    df["ADX"] = dx.rolling(period).mean()
    df["Plus_DI"] = plus_di
    df["Minus_DI"] = minus_di
    df["ATR"] = atr
    return df


def add_breakout_levels(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    df = df.copy()
    # shift(1) supaya highest high TIDAK termasuk candle hari ini sendiri
    df["HighestHigh"] = df["High"].rolling(cfg.breakout_lookback).max().shift(1)
    df["SwingLow"] = df["Low"].rolling(cfg.breakout_lookback).min().shift(1)
    return df


def add_liquidity_features(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    df = df.copy()
    df["Value"] = df["Close"] * df["Volume"]
    df["ValueAvg"] = df["Value"].rolling(cfg.volume_avg_period).mean().shift(1)
    df["VolumeAvg"] = df["Volume"].rolling(cfg.volume_avg_period).mean().shift(1)
    # count non-zero volume days
    df["TradingDays20"] = (df["Volume"] > 0).rolling(cfg.volume_avg_period).sum().shift(1)
    return df


def build_features(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    df = add_moving_averages(df, cfg)
    df = add_adx(df, cfg.adx_period)
    df = add_breakout_levels(df, cfg)
    df = add_liquidity_features(df, cfg)
    return df


# ============================================================
# 4. FUNGSI FILTER PER KRITERIA
# ============================================================

def check_trend(row: pd.Series, cfg: ScreenerConfig) -> bool:
    if pd.isna(row["MA_trend"]) or pd.isna(row["MA_confirm"]) or pd.isna(row["ADX"]):
        return False
    # Trend filter: Close > MA50 and MA50 is structurally healthy (above or within 2% of MA200)
    uptrend = (row["Close"] > row["MA_trend"]) and (row["MA_trend"] >= row["MA_confirm"] * 0.98)
    strong_trend = row["ADX"] > cfg.adx_threshold
    directional = row["Plus_DI"] > row["Minus_DI"]
    return bool(uptrend and strong_trend and directional)


def check_liquidity(row: pd.Series, cfg: ScreenerConfig) -> bool:
    if pd.isna(row["ValueAvg"]) or pd.isna(row["TradingDays20"]):
        return False
    return bool(row["ValueAvg"] >= cfg.min_transaction_value and row["TradingDays20"] >= cfg.min_trading_days)


def check_breakout(df: pd.DataFrame, as_of_date, cfg: ScreenerConfig) -> bool:
    window = df.loc[:as_of_date].tail(cfg.breakout_recency_days)
    if window.empty:
        return False
    
    # Recency: breakout happened within last N days
    recent_breakout = (window["Close"] > window["HighestHigh"]).any()
    if not recent_breakout:
        return False
        
    row = df.loc[as_of_date]
    if pd.isna(row["MA_trend"]):
        return False
        
    # Extension limit from MA50
    extension = (row["Close"] - row["MA_trend"]) / row["MA_trend"]
    if extension > cfg.max_extension_from_ma50:
        return False
        
    # Candle Quality: Close location within the day's high-low range
    candle_range = row["High"] - row["Low"]
    if candle_range > 0:
        close_location = (row["Close"] - row["Low"]) / candle_range
        if close_location < cfg.candle_close_threshold:
            return False
            
    return True


def check_volume(row: pd.Series, cfg: ScreenerConfig) -> bool:
    if pd.isna(row["VolumeAvg"]):
        return False
    return bool(row["Volume"] > cfg.volume_multiplier * row["VolumeAvg"])


def check_foreign_flow(df: pd.DataFrame, as_of_date, cfg: ScreenerConfig) -> bool:
    if "NetForeign" not in df.columns:
        return False
    window = df.loc[:as_of_date].tail(cfg.foreign_flow_days)
    if window.empty:
        return False
    positive_days = int((window["NetForeign"] > 0).sum())
    return positive_days >= cfg.min_foreign_buy_days


def calculate_risk(row: pd.Series, cfg: ScreenerConfig) -> dict:
    if pd.isna(row["ATR"]) or pd.isna(row["SwingLow"]):
        return {"risk_ok": False, "stop_loss": 0.0, "risk_pct": 1.0, "atr": 0.0}
        
    sl_atr = row["Close"] - (2 * row["ATR"])
    sl_swing = row["SwingLow"]
    
    # Hybrid SL: pick the higher/tighter one
    final_sl = max(sl_atr, sl_swing)
    
    # Calculate Risk Pct
    risk_pct = (row["Close"] - final_sl) / row["Close"] if row["Close"] > 0 else 1.0
    risk_ok = risk_pct <= cfg.max_risk_pct
    
    return {
        "risk_ok": bool(risk_ok),
        "stop_loss": float(final_sl),
        "risk_pct": float(risk_pct),
        "atr": float(row["ATR"])
    }

def find_resistances(df: pd.DataFrame, as_of_date, current_price: float, lookback: int = 120) -> List[float]:
    """Cari level resisten teknikal berdasarkan Swing Highs masa lalu."""
    window = df.loc[:as_of_date].tail(lookback)
    if len(window) < 5:
        return []
        
    highs = window['High'].values
    local_maxima = []
    
    # Deteksi Swing Highs
    for i in range(2, len(highs)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            local_maxima.append(highs[i])
            
    # Hapus duplikat dan filter yang di atas current_price (dengan margin 1%)
    resistances = sorted(list(set([r for r in local_maxima if r > current_price * 1.01])))
    
    # Cluster resistances yang berdekatan (misal beda < 3%)
    clustered = []
    for r in resistances:
        if not clustered:
            clustered.append(r)
        else:
            if (r - clustered[-1]) / clustered[-1] > 0.03:
                clustered.append(r)
                
    return clustered


# ============================================================
# 5. SCORING
# ============================================================

def score_stock(df: pd.DataFrame, as_of_date, cfg: ScreenerConfig, ihsg_bullish: bool = True) -> dict:
    row = df.loc[as_of_date]
    
    # 1. Hard Gates
    trend_ok = check_trend(row, cfg)
    liquidity_ok = check_liquidity(row, cfg)
    risk_data = calculate_risk(row, cfg)
    
    # Base failure state
    result = {
        "trend_ok": False,
        "breakout_ok": False,
        "volume_ok": False,
        "foreign_ok": False,
        "score": 0,
        "stop_loss": risk_data["stop_loss"],
        "risk_pct": risk_data["risk_pct"],
        "atr": risk_data["atr"],
        "transaction_value": float(row.get("ValueAvg", 0.0)),
        "entry_range_low": 0.0,
        "entry_range_high": 0.0,
        "tp1": None,
        "tp2": None,
        "tp3": None
    }
    
    if not (trend_ok and liquidity_ok and risk_data["risk_ok"] and ihsg_bullish):
        return result

    # 2. Soft Scoring
    breakout_ok = check_breakout(df, as_of_date, cfg)
    volume_ok = check_volume(row, cfg)
    foreign_ok = check_foreign_flow(df, as_of_date, cfg)
    
    score = 0
    if breakout_ok: score += 45
    if volume_ok: score += 35
    if foreign_ok: score += 15
    if row.get("ADX", 0) > 25: score += 5  # Strong momentum booster

    # Kalkulasi Entry Range & Take Profits jika breakout
    entry_range_low = row["Close"] * 0.98  # Buy on weakness 2%
    entry_range_high = row["Close"] * 1.02 # Buy on strength breakout 2%
    
    # Ambil resistance terdekat
    resistances = find_resistances(df, as_of_date, row["Close"])
    
    tp1 = resistances[0] if len(resistances) > 0 else None
    tp2 = resistances[1] if len(resistances) > 1 else None
    tp3 = resistances[2] if len(resistances) > 2 else None

    result.update({
        "trend_ok": trend_ok,
        "breakout_ok": breakout_ok,
        "volume_ok": volume_ok,
        "foreign_ok": foreign_ok,
        "score": score,
        "entry_range_low": float(entry_range_low),
        "entry_range_high": float(entry_range_high),
        "tp1": float(tp1) if tp1 else None,
        "tp2": float(tp2) if tp2 else None,
        "tp3": float(tp3) if tp3 else None
    })
    return result


# ============================================================
# 6. SCREENER RUNNER
# ============================================================

from app.db.models import BenchmarkPrice

def get_ihsg_regime(db: Session) -> bool:
    """Cek apakah IHSG berada di atas MA50."""
    try:
        ihsg_data = db.query(BenchmarkPrice.close).filter(BenchmarkPrice.index_code == "^JKSE").order_by(BenchmarkPrice.date.desc()).limit(50).all()
        db.rollback() # Release transaction immediately
        if len(ihsg_data) < 50:
            return True # Asumsikan bullish jika data tidak cukup
        
        closes = [float(x.close) for x in ihsg_data]
        closes.reverse()
        ma50 = sum(closes) / 50.0
        current_close = closes[-1]
        
        return current_close > ma50
    except Exception as e:
        print(f"Error checking IHSG regime: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return True


def screen_ticker(
    db: Session,
    ticker: str,
    cfg: ScreenerConfig,
    ihsg_bullish: bool = True
) -> dict:
    """Jalankan seluruh pipeline untuk satu ticker, kembalikan hasil candle terakhir."""
    ticker_code = ticker.replace(".JK", "")
    df = load_data_from_db(db, ticker_code)
    df = build_features(df, cfg)
    
    last_row = df.iloc[-1]
    
    result = score_stock(df, last_row.name, cfg, ihsg_bullish=ihsg_bullish)
    result["ticker"] = ticker_code
    result["date"] = last_row.name
    result["close"] = last_row["Close"]
    return result


def run_screener(
    db: Session,
    tickers: List[str],
    cfg: ScreenerConfig,
    save_to_db: bool = False
) -> pd.DataFrame:
    """
    Jalankan screener untuk banyak ticker sekaligus, kembalikan hasil
    terurut berdasarkan skor tertinggi.
    """
    ihsg_bullish = get_ihsg_regime(db)
    print(f"IHSG Regime: {'Bullish (> MA50)' if ihsg_bullish else 'Bearish (< MA50)'}")
    
    results = []
    for t in tickers:
        try:
            results.append(screen_ticker(db, t, cfg, ihsg_bullish=ihsg_bullish))
        except Exception as e:
            # Skip logging for expected ValueError (Data kosong)
            if "Data kosong" not in str(e):
                print(f"[SKIP] {t}: {e}")

    result_df = pd.DataFrame(results)
    if result_df.empty:
        return result_df
        
    result_df = result_df.sort_values("score", ascending=False).reset_index(drop=True)
    
    if save_to_db:
        # Hanya simpan kandidat yang lolos Hard Gates dan Breakout agar DB tidak membengkak
        db_df = result_df[(result_df["trend_ok"] == True) & (result_df["breakout_ok"] == True)]
        
        if not db_df.empty:
            # Hapus data screener untuk tanggal yang sama agar tidak duplikat (menghindari UniqueViolation)
            dates_to_clear = db_df['date'].unique()
            for d in dates_to_clear:
                db.query(ScreenerResult).filter(ScreenerResult.date == pd.to_datetime(d).date()).delete()
                
            records = []
            for _, row in db_df.iterrows():
                record = ScreenerResult(
                    date=pd.to_datetime(row['date']).date(),
                    company_code=row['ticker'],
                    score=row['score'],
                    trend_ok=row['trend_ok'],
                    breakout_ok=row['breakout_ok'],
                    volume_ok=row['volume_ok'],
                    foreign_ok=row['foreign_ok'],
                    close_price=row['close'],
                    transaction_value=row.get('transaction_value'),
                    stop_loss=row.get('stop_loss'),
                    atr=row.get('atr'),
                    risk_pct=row.get('risk_pct')
                )
                records.append(record)
            
            db.bulk_save_objects(records)
            db.commit()
            print(f"Disimpan {len(records)} hasil screener ke database.")
        else:
            print("Tidak ada kandidat breakout baru yang disimpan ke database.")
            try:
                db.rollback()
            except Exception:
                pass
        
    return result_df


# ============================================================
# 7. CONTOH PENGGUNAAN
# ============================================================

if __name__ == "__main__":
    from app.core.timezone import get_jakarta_now
    from app.db.database import SessionLocal
    
    today = get_jakarta_now()
    if today.weekday() >= 5:
        print("Hari ini adalah akhir pekan (Sabtu/Minggu). Bursa tutup, screener dilewati.")
        sys.exit(0)

    cfg = ScreenerConfig()
    db = SessionLocal()
    
    try:
        companies = db.query(Company).all()
        watchlist = [c.code for c in companies]
        db.rollback()  # Release connection immediately so it doesn't stay 'idle in transaction'
        
        print(f"Menjalankan screener untuk {len(watchlist)} emiten...")
        hasil = run_screener(db, watchlist, cfg, save_to_db=True)
        print(hasil)
    
        # Filter kandidat kuat yang lolos hard gates dan valid breakout
        if not hasil.empty:
            kandidat_kuat = hasil[(hasil["trend_ok"] == True) & (hasil["breakout_ok"] == True)]
            print("\nKandidat breakout kuat (Lolos Trend, Liquidity, Risk, Breakout):")
            print(kandidat_kuat[["ticker", "close", "score", "stop_loss", "risk_pct", "transaction_value"]])
            
            if not kandidat_kuat.empty:
                kandidat_kuat_str = kandidat_kuat.copy()
                kandidat_kuat_str['date'] = kandidat_kuat_str['date'].astype(str)
                alerts_payload = kandidat_kuat_str.replace({np.nan: None}).to_dict(orient="records")
                
                try:
                    # 1. Coba kirim via endpoint FastAPI jika backend berjalan
                    api_url = "http://localhost:8000/api/alerts/notify"
                    resp = requests.post(api_url, json={"alerts": alerts_payload}, timeout=3)
                    if resp.status_code == 200:
                        print("Berhasil mengirim sinyal ke Alert Service (WebSocket/Telegram).")
                    else:
                        raise Exception(f"HTTP {resp.status_code}")
                except Exception:
                    # 2. Fallback: kirim langsung via notifier module (misal di GitHub Actions / CLI standalone)
                    from app.services.notifier import send_telegram_alert, format_telegram_message
                    telegram_msg = format_telegram_message(alerts_payload)
                    if send_telegram_alert(telegram_msg):
                        print("Berhasil mengirim alert Telegram secara langsung.")
    finally:
        try:
            db.close()
        except Exception as e:
            print(f"[DB] Session close notice: {e}")
