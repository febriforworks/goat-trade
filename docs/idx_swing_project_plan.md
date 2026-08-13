# IDX Swing Trading Screener — Project Plan

## Ringkasan Proyek
Aplikasi/bot untuk screening saham IDX bergaya **swing trading berbasis
technical analysis** — bukan analisis fundamental. Fokus deteksi: tren,
breakout, konfirmasi volume, dan (opsional) foreign flow. Pendekatan data:
mulai dari sumber gratis dulu (yfinance + data resmi IDX), baru
pertimbangkan API berbayar kalau kebutuhan berkembang.

## Sumber Data

| Data | Sumber | Status |
|---|---|---|
| OHLCV harian & daftar emiten | yfinance (ticker `.JK`) & IDX API | Sudah jalan, tersimpan di database sendiri (`HistoricalPrice` & `DailyMarketData`) |
| Foreign flow (Foreign Buy/Sell) | idx.co.id → Data Pasar → Ringkasan Perdagangan (Ringkasan Saham / Ringkasan Broker), unduh gratis | Selesai — tersimpan di database sendiri (`DailyMarketData`) |
| Data fundamental (PER/PBV/ROE, dll) | Tidak dipakai — screener ini fokus technical, bukan fundamental | Tidak relevan untuk strategi ini |

**Catatan:** yfinance tidak reliable untuk data institusional/foreign flow
saham IDX (sering kosong) — foreign flow WAJIB dari sumber resmi IDX, bukan
dari yfinance.

## Strategi Screening (4 Kriteria Berlapis)

Skor 0–4 dihitung per saham (bukan AND filter kaku), supaya bisa
di-ranking dan di-tuning lewat backtest, baru diperketat jadi filter wajib
kalau sudah terbukti reliable:

1. **Filter Tren** — `Close > MA50 > MA200` (atau `MA20 > MA50` untuk versi
   lebih responsif), dikonfirmasi `ADX(14) > 20` supaya bukan tren yang
   lemah/sideways.
2. **Trigger Breakout** — `Close > Highest High(20)` sebelumnya (Donchian
   Channel breakout).
3. **Konfirmasi Volume** — `Volume > 1.5–2x` rata-rata volume 20 hari
   terakhir.
4. **Konfirmasi Foreign Flow** (opsional, penguat sinyal) — net foreign
   buy positif pada minimal 3 dari 5 hari terakhir.

## Arsitektur Kode

### `idx_swing_screener_framework.py`
Kerangka screening awal:
- `ScreenerConfig` — semua parameter tunable (periode MA, threshold ADX,
  lookback breakout, dll)
- `load_price_data()` / `load_foreign_flow()` — loader data (yfinance /
  file hasil parsing IDX)
- `add_moving_averages`, `add_adx`, `add_breakout_levels`,
  `add_volume_avg`, `build_features()` — kalkulasi indikator
- `check_trend/breakout/volume/foreign_flow()`, `score_stock()` — logika
  skor per kriteria
- `run_screener()` — loop banyak ticker → hasil terurut skor tertinggi

### `idx_swing_backtester.py`
Modul backtest (extend dari file di atas, import langsung dari sana):
- `BacktestConfig` — parameter stop loss, take profit, max holding
  period, risk per trade, komisi
- `Trade` — struktur satu transaksi simulasi (entry/exit/pnl)
- `simulate_ticker()` — simulasi entry/exit point-in-time untuk 1 ticker
  (tanpa look-ahead bias)
- `run_backtest()` — jalankan simulasi banyak ticker → tabel semua trade
- `build_equity_curve()` — kurva ekuitas kumulatif
- `summarize_performance()` — win rate, profit factor, max drawdown,
  breakdown alasan exit

## Metodologi Backtest

- **Point-in-time simulation** — entry direalisasikan di harga Open hari
  berikutnya setelah sinyal muncul, bukan di harga close hari sinyal
  (mencegah look-ahead bias).
- **Exit rules** — stop loss / take profit / batas waktu holding (`max_holding_days`),
  mana yang kena duluan.
- **Position sizing** — berbasis risiko per trade (% dari modal), bukan
  jumlah lot tetap.
- **Validasi in-sample vs out-of-sample** — parameter yang di-tuning di
  satu periode harus diuji ulang di periode lain yang belum pernah dilihat,
  supaya tidak overfit.
- **Durasi data** — 1 tahun cukup untuk *sanity check* pipeline (pastikan
  logic & kode jalan benar), tapi validasi strategi yang sungguhan butuh
  minimal 3–5 tahun, idealnya mencakup periode koreksi tajam IHSG (mis.
  2020 atau 2022) supaya strategi teruji lintas kondisi pasar, bukan cuma
  satu rezim (misal cuma uptrend).
- **Survivorship bias** — perlu dicek apakah data historis di database
  mencakup saham yang sudah delisting/suspend dalam periode backtest, atau
  cuma saham yang masih listed sekarang.

## Status Saat Ini

- [x] Riset platform/API data saham IDX (resmi vs gratis vs berbayar)
- [x] Data OHLCV & daftar emiten sudah ditarik via yfinance, tersimpan di
      database sendiri
- [x] Kerangka screener dasar (`idx_swing_screener_framework.py`) selesai
      — 4 kriteria + sistem skor
- [x] Modul backtest (`idx_swing_backtester.py`) selesai — simulasi trade,
      equity curve, metrik performa
- [x] Integrasi database untuk screener dan backtester

## Task Selanjutnya

- [x] Ganti watchlist hardcoded di `run_screener()` / contoh penggunaan
      dengan query dari database (mis. fungsi `get_active_tickers_from_db()`)
- [x] Bangun pipeline scraping/parsing "Ringkasan Saham" / "Ringkasan
      Broker" dari idx.co.id → langsung masuk ke DB (`fetch_past_daily.py`)
- [ ] Jalankan backtest sanity-check di atas data 1 tahun yang sudah ada
      untuk pastikan tidak ada bug atau look-ahead bias di pipeline
- [ ] Perluas historical data ke minimal 3–5 tahun (idealnya mencakup
      periode koreksi IHSG) untuk backtest yang lebih valid
- [ ] Sesuaikan `commission_pct` di `BacktestConfig` dengan biaya riil
      broker yang dipakai, dan pertimbangkan menambahkan slippage
- [ ] Implementasikan split in-sample / out-of-sample (atau walk-forward
      optimization) untuk validasi parameter sebelum dipercaya
- [ ] Setelah backtest stabil, cek survivorship bias pada data historis
- [ ] (Opsional, lanjutan) Uji scoring tertimbang (weighted score) alih-alih
      skor rata 0–4, kalau backtest menunjukkan satu kriteria jauh lebih
      prediktif dari yang lain

## Catatan Penting

- Ini kerangka teknikal untuk riset & pengembangan pribadi, **bukan**
  rekomendasi saham atau jaminan profit — semua parameter perlu divalidasi
  lewat backtest sebelum dipakai untuk keputusan trading nyata.
- Data resmi BEI (Layanan Data BEI / lisensi Market Data) berbayar untuk
  akses langsung/real-time; yang gratis adalah ringkasan harian yang bisa
  diunduh manual atau di-scrape dari idx.co.id.
