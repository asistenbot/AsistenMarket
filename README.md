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
`/laporan`, `/laporan xau`, `/intraday`, `/scalp`, `/harga`

## Variables (Railway)
`TELEGRAM_BOT_TOKEN`, `TWELVEDATA_API_KEY`, `ANTHROPIC_API_KEY` (opsional, tanpa ini laporan tetap jalan versi polos), `OWNER_CHAT_IDS`.

Analisa teknikal otomatis, bukan saran keuangan.
