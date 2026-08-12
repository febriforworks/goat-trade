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
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from app.db.models import HistoricalPrice, DailyMarketData, Company


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
    
    return combined


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
        hasil = run_screener(db, watchlist, cfg)
        print(hasil)
    
        # Contoh: ambil saham dengan skor >= 3 dari 4 kriteria
        if not hasil.empty:
            kandidat_kuat = hasil[hasil["score"] >= 3]
            print("\nKandidat breakout kuat:")
            print(kandidat_kuat)
    finally:
        db.close()
