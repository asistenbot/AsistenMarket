"""Pengaturan Asisten Market. Semua rahasia diambil dari environment variable (Railway → Variables)."""
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Chat ID Telegram yang boleh pakai bot & yang dikirimi laporan (pisahkan pakai koma).
OWNER_CHAT_IDS = [int(x) for x in os.getenv("OWNER_CHAT_IDS", "").replace(" ", "").split(",") if x]

# Model AI: yang pintar buat laporan pagi, yang cepat/murah buat update & scalping.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_MODEL_FAST = os.getenv("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")

TIMEZONE = "Asia/Jakarta"

# Daftar pair. source: "twelvedata" (emas/forex) atau "binance" (crypto).
SYMBOLS = {
    "XAUUSD": {"label": "XAU/USD (Emas)", "source": "twelvedata", "ticker": "XAU/USD", "digits": 2},
    "BTCUSDT": {"label": "BTC/USDT", "source": "binance", "ticker": "BTCUSDT", "digits": 1},
    "ETHUSDT": {"label": "ETH/USDT", "source": "binance", "ticker": "ETHUSDT", "digits": 2},
}

# Jadwal (jam WIB)
JAM_LAPORAN_PAGI = (7, 0)
JAM_UPDATE_INTRADAY = [(11, 0), (15, 0), (19, 0), (23, 0)]
SCALP_JAM_MULAI = 14   # sesi London
SCALP_JAM_SELESAI = 24  # sampai tengah malam (sesi New York)
SCALP_TIAP_MENIT = 15
