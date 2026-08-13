"""
IDX Swing Trading Screener - Modul Backtest
=============================================
Extend dari `idx_swing_screener_framework.py` untuk mensimulasikan
strategi swing trading berbasis sinyal screener (trend + breakout +
volume + foreign flow) secara historis.

Taruh file ini di direktori yang sama dengan
`idx_swing_screener_framework.py` supaya import di bawah berfungsi.

Dependency:
    pip install pandas numpy yfinance

Alur pemakaian singkat:
    1. Ambil & siapkan data harga (load_price_data + build_features)
       dari modul screener untuk tiap ticker di watchlist.
    2. Panggil run_backtest() untuk mensimulasikan semua ticker sekaligus.
    3. Panggil summarize_performance() untuk lihat win rate, profit
       factor, max drawdown, dll.

Catatan penting:
- Simulasi ini MENYEDERHANAKAN eksekusi: entry di harga Open candle
  berikutnya setelah sinyal, exit dicek mulai hari berikutnya juga
  (tidak exit di hari yang sama dengan entry).
- Saat ini hanya mendukung 1 posisi terbuka per ticker pada satu waktu
  (belum pyramiding / multiple entries pada ticker yang sama).
- Slippage belum dimodelkan secara eksplisit -- kalau perlu, tambahkan
  sebagai penyesuaian pada entry_price/exit_price sebelum dipakai.
- Ini alat simulasi teknikal, BUKAN jaminan hasil di real trading.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.screener import (
    ScreenerConfig,
    build_features,
    load_data_from_db,
    score_stock,
)
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import Company, IndexMembership


# ============================================================
# 1. KONFIGURASI BACKTEST
# ============================================================

@dataclass
class BacktestConfig:
    entry_score_threshold: int = 95       # Minimal skor 95 (Breakout + Volume wajib)
    max_holding_days: int = 999           # Dimatikan agar profit bisa berjalan sampai menyentuh SL/TP
    risk_per_trade_pct: float = 0.02      # risiko 2% dari modal per trade
    initial_capital: float = 100_000_000  # contoh: Rp100 juta, sesuaikan
    buy_fee_pct: float = 0.0015           # 0.15% fee beli
    sell_fee_pct: float = 0.0025          # 0.25% fee jual
    max_volume_participation_pct: float = 0.1 # 10% dari VolumeAvg


# ============================================================
# 2. STRUKTUR TRADE
# ============================================================

@dataclass
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    stop_price: float
    target_price: float
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "stop_loss" | "take_profit" | "time_exit"
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None

    def close(self, exit_date, exit_price, exit_reason, buy_fee_pct: float, sell_fee_pct: float):
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.exit_reason = exit_reason

        gross_pnl = (exit_price - self.entry_price) * self.shares
        entry_cost = self.entry_price * self.shares * buy_fee_pct
        exit_cost = exit_price * self.shares * sell_fee_pct
        self.pnl = gross_pnl - entry_cost - exit_cost
        self.pnl_pct = (exit_price - self.entry_price) / self.entry_price


# ============================================================
# 3. SIMULASI SATU TICKER (point-in-time, no look-ahead)
# ============================================================

def simulate_ticker(
    ticker: str,
    df: pd.DataFrame,
    screener_cfg: ScreenerConfig,
    backtest_cfg: BacktestConfig,
) -> List[Trade]:
    """
    Simulasikan strategi pada satu ticker.
    `df` harus sudah melalui build_features() dari modul screener
    (punya kolom MA_trend, MA_confirm, ADX, HighestHigh, VolumeAvg, dst).
    """
    trades: List[Trade] = []
    open_trade: Optional[Trade] = None
    entry_idx: Optional[int] = None

    dates = df.index

    for i in range(len(dates) - 1):  # -1 karena entry direalisasikan di hari berikutnya
        today = dates[i]
        tomorrow = dates[i + 1]
        row = df.loc[today]

        # --- 1. Kelola posisi terbuka dulu: cek kondisi exit ---
        if open_trade is not None:
            next_row = df.loc[tomorrow]
            holding_days = (i + 1) - entry_idx
            exit_reason = None
            exit_price = None

            # Skip exit if suspended
            is_suspended = next_row.get("is_suspended", False)
            if is_suspended:
                continue

            arb_limit = next_row.get("arb_limit", pd.NA)

            # Asumsi konservatif: kalau Low & High sama-sama kena
            # stop/target di hari yang sama, stop loss dicek duluan.
            if next_row["Low"] <= open_trade.stop_price:
                exit_reason = "stop_loss"
                exit_price = open_trade.stop_price
            elif next_row["High"] >= open_trade.target_price:
                exit_reason = "take_profit"
                exit_price = open_trade.target_price
            elif holding_days >= backtest_cfg.max_holding_days:
                exit_reason = "time_exit"
                exit_price = next_row["Open"]
                
            if exit_reason:
                # Conservative rule: if trying to exit, but price opens at or below ARB, skip exit
                if not pd.isna(arb_limit) and next_row["Open"] <= arb_limit:
                    continue
                    
                open_trade.close(tomorrow, exit_price, exit_reason, backtest_cfg.buy_fee_pct, backtest_cfg.sell_fee_pct)
                trades.append(open_trade)
                open_trade = None
                entry_idx = None

        # --- 2. Cek sinyal entry baru (hanya kalau belum ada posisi terbuka) ---
        if open_trade is None:
            result = score_stock(df, today, screener_cfg)
            if result["score"] >= backtest_cfg.entry_score_threshold:
                next_row = df.loc[tomorrow]
                
                # Cek Suspend & ARA
                is_suspended = next_row.get("is_suspended", False)
                if is_suspended:
                    continue
                    
                ara_limit = next_row.get("ara_limit", pd.NA)
                if not pd.isna(ara_limit) and next_row["Open"] >= ara_limit:
                    # Gagal beli karena buka di ARA
                    continue
                    
                entry_price = next_row["Open"]
                
                # Gunakan Stop Loss dinamis dari screener (ATR/Swing Hybrid)
                stop_price = result["stop_loss"]
                
                # Jika stop loss sama atau lebih besar dari entry (aneh), fallback ke 5%
                if stop_price >= entry_price or pd.isna(stop_price):
                    stop_price = entry_price * 0.95
                    
                # Risk to Reward = 1:3 (Kembali ke Let Profit Run)
                risk_pts = entry_price - stop_price
                target_price = entry_price + (risk_pts * 3)

                risk_amount = backtest_cfg.initial_capital * backtest_cfg.risk_per_trade_pct
                risk_per_share = entry_price - stop_price
                shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
                
                # Bounding position sizing to not exceed available capital
                max_affordable_shares = int(backtest_cfg.initial_capital / entry_price)
                if shares > max_affordable_shares:
                    shares = max_affordable_shares
                
                # Batas likuiditas: maksimum porsi dari volume rata-rata
                vol_avg = row.get("VolumeAvg", 0)
                max_shares = int(vol_avg * backtest_cfg.max_volume_participation_pct)
                
                if max_shares > 0:
                    shares = min(shares, max_shares)

                if shares > 0:
                    open_trade = Trade(
                        ticker=ticker,
                        entry_date=tomorrow,
                        entry_price=entry_price,
                        shares=shares,
                        stop_price=stop_price,
                        target_price=target_price
                    )
                    entry_idx = i + 1

    return trades


# ============================================================
# 4. SIMULASI BANYAK TICKER
# ============================================================

def run_backtest(
    price_data: Dict[str, pd.DataFrame],  # {ticker: DataFrame sudah build_features()}
    screener_cfg: ScreenerConfig,
    backtest_cfg: BacktestConfig,
) -> pd.DataFrame:
    """
    Jalankan simulasi untuk banyak ticker sekaligus, gabungkan semua
    trade jadi satu tabel untuk dianalisa.
    """
    all_trades: List[Trade] = []

    for ticker, df in price_data.items():
        trades = simulate_ticker(ticker, df, screener_cfg, backtest_cfg)
        all_trades.extend(trades)

    if not all_trades:
        return pd.DataFrame()

    trades_df = pd.DataFrame([vars(t) for t in all_trades])
    trades_df = trades_df.sort_values("entry_date").reset_index(drop=True)
    return trades_df


def build_equity_curve(trades_df: pd.DataFrame, backtest_cfg: BacktestConfig) -> pd.DataFrame:
    """
    Bangun kurva ekuitas kumulatif dari urutan trade, diurutkan
    berdasarkan tanggal EXIT (karena di situ PnL benar-benar terealisasi).
    """
    if trades_df.empty:
        return pd.DataFrame()

    num_tickers = len(trades_df['ticker'].unique())
    portfolio_initial_capital = backtest_cfg.initial_capital * num_tickers

    closed = trades_df.dropna(subset=["exit_date"]).sort_values("exit_date").copy()
    closed["cumulative_pnl"] = closed["pnl"].cumsum()
    closed["equity"] = portfolio_initial_capital + closed["cumulative_pnl"]
    return closed


# ============================================================
# 5. METRIK PERFORMA
# ============================================================

def summarize_performance(trades_df: pd.DataFrame, backtest_cfg: BacktestConfig) -> dict:
    closed = trades_df.dropna(subset=["exit_date"])
    if closed.empty:
        return {"total_trades": 0}

    wins = closed[closed["pnl"] > 0]
    losses = closed[closed["pnl"] <= 0]

    total_profit = wins["pnl"].sum()
    total_loss = abs(losses["pnl"].sum())

    equity = build_equity_curve(trades_df, backtest_cfg)
    running_max = equity["equity"].cummax()
    drawdown = (equity["equity"] - running_max) / running_max
    max_drawdown_pct = drawdown.min() if not drawdown.empty else 0.0

    num_tickers = len(trades_df['ticker'].unique())
    portfolio_initial_capital = backtest_cfg.initial_capital * num_tickers
    total_pnl = closed["pnl"].sum()
    total_return_pct = total_pnl / portfolio_initial_capital if portfolio_initial_capital > 0 else 0.0

    return {
        "total_trades": len(closed),
        "win_rate": len(wins) / len(closed) if len(closed) else 0.0,
        "avg_win_pct": wins["pnl_pct"].mean() if not wins.empty else 0.0,
        "avg_loss_pct": losses["pnl_pct"].mean() if not losses.empty else 0.0,
        "profit_factor": (total_profit / total_loss) if total_loss > 0 else np.nan,
        "total_pnl": total_pnl,
        "portfolio_initial_capital": portfolio_initial_capital,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "exit_reason_breakdown": closed["exit_reason"].value_counts().to_dict(),
    }


# ============================================================
# 6. CONTOH PENGGUNAAN
# ============================================================

if __name__ == "__main__":
    screener_cfg = ScreenerConfig()
    backtest_cfg = BacktestConfig()
    
    db = SessionLocal()

    try:
        # Mengambil emiten LQ45 yang masih aktif dari tabel IndexMembership
        memberships = db.query(IndexMembership).filter(
            IndexMembership.index_code == 'LQ45',
            IndexMembership.end_date == None
        ).all()
        watchlist = [m.company_code for m in memberships]
        if not watchlist:
            watchlist = ["BBCA", "BBRI", "TLKM", "ASII", "ADRO"]

        price_data = {}
        print(f"Menyiapkan data histori untuk {len(watchlist)} emiten...")
        for t in watchlist:
            try:
                df = load_data_from_db(db, t)
                df = build_features(df, screener_cfg)
                price_data[t] = df
            except Exception as e:
                print(f"[SKIP] {t}: {e}")

        print("Menjalankan backtest...")
        trades_df = run_backtest(price_data, screener_cfg, backtest_cfg)
        
        if not trades_df.empty:
            # Format tampilan dataframe
            display_df = trades_df.copy()
            if 'pnl' in display_df.columns:
                display_df['pnl'] = display_df['pnl'].apply(lambda x: f"Rp {x:,.0f}" if pd.notna(x) else "")
            if 'pnl_pct' in display_df.columns:
                display_df['pnl_pct'] = display_df['pnl_pct'].apply(lambda x: f"{x:.2%}" if pd.notna(x) else "")
            
            print(display_df.to_string())

            stats = summarize_performance(trades_df, backtest_cfg)
            print("\nRingkasan performa:")
            print(f"  Total Trades: {stats['total_trades']}")
            print(f"  Win Rate: {stats['win_rate']:.2%}")
            print(f"  Avg Win Pct: {stats['avg_win_pct']:.2%}")
            print(f"  Avg Loss Pct: {stats['avg_loss_pct']:.2%}")
            
            profit_factor = stats['profit_factor']
            pf_str = f"{profit_factor:.2f}" if not pd.isna(profit_factor) else "N/A"
            print(f"  Profit Factor: {pf_str}")
            
            print(f"  Total Capital Deployed: Rp {stats['portfolio_initial_capital']:,.0f}")
            print(f"  Total PnL (Net Profit): Rp {stats['total_pnl']:,.0f}")
            print(f"  Total Return Pct: {stats['total_return_pct']:.2%}")
            print(f"  Max Drawdown: {stats['max_drawdown_pct']:.2%}")
            print(f"  Exit Reason Breakdown: {stats['exit_reason_breakdown']}")
        else:
            print("Tidak ada trade yang tereksekusi.")
    finally:
        db.close()
