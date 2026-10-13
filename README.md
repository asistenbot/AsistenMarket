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

## Pencatat hasil scalping
`tracker.py` mencatat tiap ide scalping ke `/data/sinyal.json` (volume Railway), cek tiap 10 menit apakah kena TP1/TP2/SL, kirim hasilnya ke topik Scalping, dan rekap mingguan tiap Minggu 21:00 WIB.

## Variables (Railway)
`TELEGRAM_BOT_TOKEN`, `TWELVEDATA_API_KEY`, `ANTHROPIC_API_KEY` (opsional, tanpa ini laporan tetap jalan versi polos), `OWNER_CHAT_IDS`.

Analisa teknikal otomatis, bukan saran keuangan.
