# Asisten Market

Bot Telegram analisa XAU/USD dan crypto (BTC, ETH, SOL, SUI, TAO, HYPE, ONDO, ASTER).

| Peran | File | Tugas |
|---|---|---|
| Kurir data | `data.py` | Ambil candle dari Binance (crypto) dan TwelveData (emas) |
| Analis swing | `analysts.py` | 3M, 1M, 1W, 1D |
| Analis intraday | `analysts.py` | 4H, 1H, 15m |
| Scalper | `scalper.py` | Setup 5m yang searah trend 15m & 1H |
| Manajer | `manager.py` | Rangkum pakai AI, kirim ke Telegram |

Angka (EMA, RSI, ATR, support/resistance) dihitung kode di `indicators.py`; AI cuma menulis narasinya.

## Jadwal (WIB)
- 07:00 laporan pagi lengkap
- 11:00, 15:00, 19:00, 23:00 update intraday
- 14:00–24:00 cek scalping tiap 15 menit, kirim kalau ada setup

## Perintah
`/laporan`, `/laporan xau`, `/laporan semua`, `/intraday`, `/scalp`, `/harga`, `/rekap`, `/rekap 30`

## Sniper entry
`sniper.py` cari rencana limit order di order block / support-resistance 1H, searah trend 4H/1D, RR 1:3 sampai 1:6. Scan otomatis tiap jam (cuma kirim rencana baru), pantau tiap 5 menit: alarm waktu harga mendekat, waktu entry kena, dan hasil TP/SL. Perintah: `/sniper`, `/sniper xau`, `/sniper aktif`. Topik: `TOPIC_SNIPER` (kosong = ikut topik Scalping).

## Scalper v3 (dipakai) & backtest
Dipilih lewat backtest 60 hari ke data asli, sudah dipotong biaya (crypto 0.1%, emas 0.02% per transaksi), dicek di 2 periode terpisah.
v3 = setup lama + ADX 15m >= 20 + jarak SL minimal 0.2% dari harga. XAU dikeluarkan dari scalping otomatis (SCALP_SKIP).
`/uji` atau `/uji 14` menjalankan backtest v3 vs versi lama. Env `BACKTEST_SAAT_START=1` menjalankan eksperimen 60 hari waktu bot nyala (hasil di log).

## Pencatat hasil scalping
`tracker.py` mencatat tiap ide scalping ke `/data/sinyal.json` (volume Railway), cek tiap 10 menit apakah kena TP1/TP2/SL, kirim hasilnya ke topik Scalping, dan rekap mingguan tiap Minggu 21:00 WIB.

## Variables (Railway)
`TELEGRAM_BOT_TOKEN`, `TWELVEDATA_API_KEY`, `ANTHROPIC_API_KEY` (opsional, tanpa ini laporan tetap jalan versi polos), `OWNER_CHAT_IDS`.

Analisa teknikal otomatis, bukan saran keuangan.
