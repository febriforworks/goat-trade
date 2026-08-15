"""
IDX Swing Trading Screener - Modul Backtest
=============================================
Simulasi strategi swing trading berbasis sinyal screener (trend + breakout +
volume + foreign flow) secara historis dengan manajemen risiko institusional:
  1. Dynamic Universe Selection (Kompas100 / Top Liquid Stocks > Rp 2 Miliar/hari)
  2. Point-in-Time IHSG Regime Filter (Hanya entry saat IHSG > MA50)
  3. Dynamic Risk:Reward (Stop Loss ATR / Swing Low Hybrid)
  4. Breakeven Protection (+1.5R Trigger untuk memberi ruang retest)
  5. Trailing Stop (MA20 saat posisi dalam profit)
  6. Position Sizing berbasis Fixed Fractional Risk (2% per trade)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

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
from sqlalchemy import func
from app.db.database import SessionLocal
from app.db.models import Company, IndexMembership, HistoricalPrice, DailyMarketData, BenchmarkPrice


# ============================================================
# 1. KONFIGURASI BACKTEST
# ============================================================

@dataclass
class BacktestConfig:
    entry_score_threshold: int = 75       # Minimal skor 75 (Breakout 45 + Volume 35 = 80)
    max_holding_days: int = 40            # Maksimal hari simpan swing trading
    risk_per_trade_pct: float = 0.02      # Risiko 2% dari modal per trade
    initial_capital: float = 100_000_000  # Modal awal: Rp100 juta
    buy_fee_pct: float = 0.0015           # 0.15% fee beli
    sell_fee_pct: float = 0.0025          # 0.25% fee jual
    max_volume_participation_pct: float = 0.1 # 10% dari VolumeAvg
    be_trigger_r: float = 1.5             # Pindahkan SL ke Breakeven saat profit >= 1.5R
    use_trailing_stop: bool = True        # Aktifkan trailing stop (MA20) saat dalam posisi profit
    filter_ihsg_regime: bool = True       # Filter Point-in-time: hanya beli saat IHSG > MA50
    max_risk_pct_per_trade: float = 0.07  # Batas risiko stop loss maksimal 7%


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
    exit_reason: Optional[str] = None  # "stop_loss" | "trailing_stop" | "take_profit" | "time_exit"
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
    ihsg_bullish_dates: Optional[Set[pd.Timestamp]] = None,
) -> List[Trade]:
    """
    Simulasikan strategi pada satu ticker.
    `df` harus sudah melalui build_features() dari modul screener.
    """
    trades: List[Trade] = []
    open_trade: Optional[Trade] = None
    entry_idx: Optional[int] = None
    initial_risk_pts: float = 0.0
    is_be_activated: bool = False

    dates = df.index

    for i in range(len(dates) - 1):  # -1 karena entry direalisasikan di hari berikutnya
        today = dates[i]
        tomorrow = dates[i + 1]
        row = df.loc[today]

        # --- 1. Kelola posisi terbuka dulu: cek kondisi exit & update trailing stop ---
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

            # Breakeven Rule: Jika High mencapai >= Entry + (be_trigger_r * Risk), geser SL ke BE + fee
            if backtest_cfg.be_trigger_r > 0 and not is_be_activated:
                if next_row["High"] >= open_trade.entry_price + (backtest_cfg.be_trigger_r * initial_risk_pts):
                    is_be_activated = True
                    open_trade.stop_price = max(open_trade.stop_price, open_trade.entry_price * 1.005)

            # Trailing Stop: Jika posisi sudah untung / lolos Breakeven, trail SL mengikuti MA20
            if backtest_cfg.use_trailing_stop and is_be_activated:
                ma_short = row.get("MA_short", 0)
                if pd.notna(ma_short) and ma_short > open_trade.stop_price:
                    open_trade.stop_price = float(ma_short)

            # Asumsi konservatif: kalau Low & High sama-sama kena
            # stop/target di hari yang sama, stop loss dicek duluan.
            if next_row["Low"] <= open_trade.stop_price:
                exit_reason = "trailing_stop" if is_be_activated else "stop_loss"
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
                initial_risk_pts = 0.0
                is_be_activated = False

        # --- 2. Cek sinyal entry baru (hanya kalau belum ada posisi terbuka) ---
        if open_trade is None:
            # Point-in-Time IHSG Regime Filter
            if backtest_cfg.filter_ihsg_regime and ihsg_bullish_dates is not None:
                if today not in ihsg_bullish_dates:
                    continue

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
                    
                # Pastikan jarak stop loss wajar antara 3% s/d max_risk_pct_per_trade
                risk_pct = (entry_price - stop_price) / entry_price
                if risk_pct < 0.03:
                    stop_price = entry_price * 0.97
                elif risk_pct > backtest_cfg.max_risk_pct_per_trade:
                    stop_price = entry_price * (1 - backtest_cfg.max_risk_pct_per_trade)

                initial_risk_pts = entry_price - stop_price
                target_price = entry_price + (initial_risk_pts * 2.5) # R:R = 1:2.5

                risk_amount = backtest_cfg.initial_capital * backtest_cfg.risk_per_trade_pct
                shares = int(risk_amount / initial_risk_pts) if initial_risk_pts > 0 else 0
                
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
                    is_be_activated = False

    return trades


# ============================================================
# 4. SIMULASI BANYAK TICKER
# ============================================================

def run_backtest(
    price_data: Dict[str, pd.DataFrame],
    screener_cfg: ScreenerConfig,
    backtest_cfg: BacktestConfig,
    ihsg_bullish_dates: Optional[Set[pd.Timestamp]] = None,
) -> pd.DataFrame:
    """
    Jalankan simulasi untuk banyak ticker sekaligus, gabungkan semua
    trade jadi satu tabel untuk dianalisa.
    """
    all_trades: List[Trade] = []

    for ticker, df in price_data.items():
        trades = simulate_ticker(ticker, df, screener_cfg, backtest_cfg, ihsg_bullish_dates=ihsg_bullish_dates)
        all_trades.extend(trades)

    if not all_trades:
        return pd.DataFrame()

    trades_df = pd.DataFrame([vars(t) for t in all_trades])
    trades_df = trades_df.sort_values("entry_date").reset_index(drop=True)
    return trades_df


def build_equity_curve(trades_df: pd.DataFrame, backtest_cfg: BacktestConfig) -> pd.DataFrame:
    """
    Bangun kurva ekuitas kumulatif dari urutan trade.
    """
    if trades_df.empty:
        return pd.DataFrame()

    closed = trades_df.dropna(subset=["exit_date"]).sort_values("exit_date").copy()
    closed["cumulative_pnl"] = closed["pnl"].cumsum()
    closed["equity"] = backtest_cfg.initial_capital + closed["cumulative_pnl"]
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

    total_profit = wins["pnl"].sum() if not wins.empty else 0.0
    total_loss = abs(losses["pnl"].sum()) if not losses.empty else 0.0

    equity = build_equity_curve(trades_df, backtest_cfg)
    running_max = equity["equity"].cummax()
    drawdown = (equity["equity"] - running_max) / running_max
    max_drawdown_pct = drawdown.min() if not drawdown.empty else 0.0

    total_pnl = closed["pnl"].sum()
    total_return_pct = total_pnl / backtest_cfg.initial_capital if backtest_cfg.initial_capital > 0 else 0.0

    # Hitung rata-rata hari holding
    holding_days_series = (pd.to_datetime(closed["exit_date"]) - pd.to_datetime(closed["entry_date"])).dt.days
    avg_holding_days = holding_days_series.mean() if not holding_days_series.empty else 0.0

    return {
        "total_trades": len(closed),
        "win_rate": len(wins) / len(closed) if len(closed) else 0.0,
        "avg_win_pct": wins["pnl_pct"].mean() if not wins.empty else 0.0,
        "avg_loss_pct": losses["pnl_pct"].mean() if not losses.empty else 0.0,
        "profit_factor": (total_profit / total_loss) if total_loss > 0 else np.nan,
        "total_pnl": total_pnl,
        "initial_capital": backtest_cfg.initial_capital,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "avg_holding_days": avg_holding_days,
        "exit_reason_breakdown": closed["exit_reason"].value_counts().to_dict(),
    }


def get_active_watchlist(db: Session, min_adv: float = 2_000_000_000, top_n: int = 100) -> List[str]:
    """
    Ambil emiten terlikuid di database berdasarkan transaksi harian terbaru
    untuk mencakup Kompas100 dan saham momentum mid-caps.
    """
    try:
        max_d = db.query(func.max(DailyMarketData.date)).scalar()
        if max_d:
            res = db.query(DailyMarketData.company_code).filter(
                DailyMarketData.date == max_d,
                DailyMarketData.close * DailyMarketData.volume >= min_adv
            ).order_by((DailyMarketData.close * DailyMarketData.volume).desc()).limit(top_n).all()
            if res:
                return [r[0] for r in res]
    except Exception as e:
        print(f"Error querying active watchlist: {e}")

    # Fallback ke LQ45 jika query gagal
    memberships = db.query(IndexMembership).filter(
        IndexMembership.index_code == 'LQ45',
        IndexMembership.end_date == None
    ).all()
    return [m.company_code for m in memberships] if memberships else ["BBCA", "BBRI", "TLKM", "ASII", "ADRO"]


# ============================================================
# 6. RUNNER
# ============================================================

if __name__ == "__main__":
    screener_cfg = ScreenerConfig()
    backtest_cfg = BacktestConfig()
    
    db = SessionLocal()

    try:
        # 1. Load IHSG Benchmark Regime
        ihsg_rows = db.query(BenchmarkPrice.date, BenchmarkPrice.close).filter(
            BenchmarkPrice.index_code == "^JKSE"
        ).order_by(BenchmarkPrice.date.asc()).all()

        ihsg_bullish_dates = set()
        if ihsg_rows:
            ihsg_df = pd.DataFrame([(r.date, float(r.close)) for r in ihsg_rows], columns=['date', 'close']).set_index('date')
            ihsg_df.index = pd.to_datetime(ihsg_df.index)
            ihsg_df['MA50'] = ihsg_df['close'].rolling(50).mean()
            ihsg_bullish_dates = set(ihsg_df[ihsg_df['close'] > ihsg_df['MA50']].index)
            print(f"IHSG Regime Filter Aktif: {len(ihsg_bullish_dates)} hari bullish terdeteksi.")

        # 2. Mengambil emiten terlikuid (Kompas100 / High-Turnover stocks)
        watchlist = get_active_watchlist(db, min_adv=2_000_000_000, top_n=100)

        price_data = {}
        print(f"Menyiapkan data histori untuk {len(watchlist)} emiten terlikuid...")
        for t in watchlist:
            try:
                df = load_data_from_db(db, t)
                if len(df) >= 60:
                    df = build_features(df, screener_cfg)
                    price_data[t] = df
            except Exception as e:
                if "Data kosong" not in str(e):
                    print(f"[SKIP] {t}: {e}")

        print(f"Menjalankan backtest untuk {len(price_data)} emiten...")
        trades_df = run_backtest(price_data, screener_cfg, backtest_cfg, ihsg_bullish_dates=ihsg_bullish_dates)
        
        if not trades_df.empty:
            # Format tampilan dataframe
            display_df = trades_df.copy()
            if 'pnl' in display_df.columns:
                display_df['pnl'] = display_df['pnl'].apply(lambda x: f"Rp {x:,.0f}" if pd.notna(x) else "")
            if 'pnl_pct' in display_df.columns:
                display_df['pnl_pct'] = display_df['pnl_pct'].apply(lambda x: f"{x:.2%}" if pd.notna(x) else "")
            
            print(display_df.to_string())

            stats = summarize_performance(trades_df, backtest_cfg)
            print("\n" + "="*50)
            print("RINGKASAN PERFORMA BACKTEST SWING TRADING:")
            print("="*50)
            print(f"  Total Trades             : {stats['total_trades']}")
            print(f"  Win Rate                 : {stats['win_rate']:.2%}")
            print(f"  Avg Win Pct              : {stats['avg_win_pct']:.2%}")
            print(f"  Avg Loss Pct             : {stats['avg_loss_pct']:.2%}")
            
            profit_factor = stats['profit_factor']
            pf_str = f"{profit_factor:.2f}" if not pd.isna(profit_factor) else "N/A"
            print(f"  Profit Factor            : {pf_str}")
            
            print(f"  Modal Awal (Capital)     : Rp {stats['initial_capital']:,.0f}")
            print(f"  Total PnL (Net Profit)   : Rp {stats['total_pnl']:,.0f}")
            print(f"  Total Return Pct         : {stats['total_return_pct']:.2%}")
            print(f"  Max Drawdown             : {stats['max_drawdown_pct']:.2%}")
            print(f"  Avg Holding Days         : {stats['avg_holding_days']:.1f} hari")
            print(f"  Exit Reason Breakdown    : {stats['exit_reason_breakdown']}")
            print("="*50)
        else:
            print("Tidak ada trade yang tereksekusi.")
    finally:
        db.close()
