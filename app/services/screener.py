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
    adx_threshold: float = 20.0
    breakout_lookback: int = 20
    volume_avg_period: int = 20
    volume_multiplier: float = 1.5
    foreign_flow_days: int = 5
    min_foreign_buy_days: int = 3  # minimal hari net buy dalam window di atas


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
    return df


def add_breakout_levels(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    df = df.copy()
    # shift(1) supaya highest high TIDAK termasuk candle hari ini sendiri
    df["HighestHigh"] = df["High"].rolling(cfg.breakout_lookback).max().shift(1)
    return df


def add_volume_avg(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    df = df.copy()
    df["VolumeAvg"] = df["Volume"].rolling(cfg.volume_avg_period).mean().shift(1)
    return df


def build_features(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    df = add_moving_averages(df, cfg)
    df = add_adx(df, cfg.adx_period)
    df = add_breakout_levels(df, cfg)
    df = add_volume_avg(df, cfg)
    return df


# ============================================================
# 4. FUNGSI FILTER PER KRITERIA
# ============================================================

def check_trend(row: pd.Series, cfg: ScreenerConfig) -> bool:
    if pd.isna(row["MA_trend"]) or pd.isna(row["MA_confirm"]) or pd.isna(row["ADX"]):
        return False
    uptrend = row["Close"] > row["MA_trend"] > row["MA_confirm"]
    strong_trend = row["ADX"] > cfg.adx_threshold
    return bool(uptrend and strong_trend)


def check_breakout(row: pd.Series) -> bool:
    if pd.isna(row["HighestHigh"]):
        return False
    return bool(row["Close"] > row["HighestHigh"])


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


# ============================================================
# 5. SCORING
# ============================================================

def score_stock(df: pd.DataFrame, as_of_date, cfg: ScreenerConfig) -> dict:
    """
    Skor per kriteria (bukan strict AND filter) supaya kamu bisa melihat
    saham mana yang paling banyak kriteria terpenuhi lalu diranking,
    daripada langsung dibuang begitu satu syarat gagal.
    """
    row = df.loc[as_of_date]
    trend_ok = check_trend(row, cfg)
    breakout_ok = check_breakout(row)
    volume_ok = check_volume(row, cfg)
    foreign_ok = check_foreign_flow(df, as_of_date, cfg)

    score = sum([trend_ok, breakout_ok, volume_ok, foreign_ok])

    return {
        "trend_ok": trend_ok,
        "breakout_ok": breakout_ok,
        "volume_ok": volume_ok,
        "foreign_ok": foreign_ok,
        "score": score,
    }


# ============================================================
# 6. SCREENER RUNNER
# ============================================================

def screen_ticker(
    db: Session,
    ticker: str,
    cfg: ScreenerConfig,
) -> dict:
    """Jalankan seluruh pipeline untuk satu ticker, kembalikan hasil candle terakhir."""
    ticker_code = ticker.replace(".JK", "")
    df = load_data_from_db(db, ticker_code)
    df = build_features(df, cfg)
    
    last_row = df.iloc[-1]
    
    result = score_stock(df, last_row.name, cfg)
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
    results = []
    for t in tickers:
        try:
            results.append(screen_ticker(db, t, cfg))
        except Exception as e:
            print(f"[SKIP] {t}: {e}")

    result_df = pd.DataFrame(results)
    if result_df.empty:
        return result_df
        
    result_df = result_df.sort_values("score", ascending=False).reset_index(drop=True)
    
    if save_to_db:
        # Save to database
        records = []
        for _, row in result_df.iterrows():
            record = ScreenerResult(
                date=pd.to_datetime(row['date']).date(),
                company_code=row['ticker'],
                score=row['score'],
                trend_ok=row['trend_ok'],
                breakout_ok=row['breakout_ok'],
                volume_ok=row['volume_ok'],
                foreign_ok=row['foreign_ok'],
                close_price=row['close']
            )
            # Use merge to handle duplicates (if re-running on same date)
            db.merge(record)
        db.commit()
        print(f"Disimpan {len(records)} hasil screener ke database.")
        
    return result_df


# ============================================================
# 7. CONTOH PENGGUNAAN
# ============================================================

if __name__ == "__main__":
    from app.db.database import SessionLocal
    
    cfg = ScreenerConfig()
    db = SessionLocal()
    
    try:
        # Ambil 100 perusahaan pertama sebagai contoh, 
        # karena memproses semua saham tanpa paralel bisa lambat.
        companies = db.query(Company).limit(100).all()
        watchlist = [c.code for c in companies]
        
        print(f"Menjalankan screener untuk {len(watchlist)} emiten...")
        hasil = run_screener(db, watchlist, cfg, save_to_db=True)
        print(hasil)
    
        # Contoh: ambil saham dengan skor >= 3 dari 4 kriteria
        if not hasil.empty:
            kandidat_kuat = hasil[hasil["score"] >= 3]
            print("\nKandidat breakout kuat:")
            print(kandidat_kuat)
            
            # Send payload to internal FastAPI endpoint
            if not kandidat_kuat.empty:
                # Convert DataFrame to list of dicts for JSON serialization
                # We need to replace NaN with None and handle non-standard types
                alerts_payload = kandidat_kuat.replace({np.nan: None}).to_dict(orient="records")
                
                try:
                    # Asumsikan backend berjalan di localhost:8000
                    api_url = "http://localhost:8000/api/alerts/notify"
                    resp = requests.post(api_url, json={"alerts": alerts_payload}, timeout=5)
                    if resp.status_code == 200:
                        print("Berhasil mengirim sinyal ke Alert Service (WebSocket/Telegram).")
                    else:
                        print(f"Gagal mengirim sinyal: HTTP {resp.status_code}")
                except Exception as e:
                    print(f"Error menghubungi Alert Service: {e}")
    finally:
        db.close()
