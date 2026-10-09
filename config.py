"""Pengaturan Asisten Market. Semua rahasia diambil dari environment variable (Railway → Variables)."""
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Chat ID Telegram yang boleh pakai bot & yang dikirimi laporan (pisahkan pakai koma).
OWNER_CHAT_IDS = [int(x) for x in os.getenv("OWNER_CHAT_IDS", "").replace(" ", "").split(",") if x]

# Grup Telegram bertopik (opsional). Kalau kosong, laporan dikirim ke chat pribadi owner.
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0") or 0)
TOPIC_PAGI = int(os.getenv("TOPIC_PAGI", "0") or 0)
TOPIC_INTRADAY = int(os.getenv("TOPIC_INTRADAY", "0") or 0)
TOPIC_SCALP = int(os.getenv("TOPIC_SCALP", "0") or 0)

# Otomatis atau cuma kalau diminta (1 = otomatis, 0 = pakai perintah aja)
AUTO_INTRADAY = os.getenv("AUTO_INTRADAY", "0") == "1"   # pakai AI → default manual biar hemat
AUTO_SCALP = os.getenv("AUTO_SCALP", "1") == "1"         # tanpa AI → gratis, default otomatis

# Model AI: yang pintar buat laporan pagi, yang cepat/murah buat update & scalping.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_MODEL_FAST = os.getenv("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")

TIMEZONE = "Asia/Jakarta"

# Daftar pair. source: "twelvedata" (emas/forex) atau "binance" (crypto).
SYMBOLS = {
    "XAUUSD": {"label": "XAU/USD (Emas)", "source": "twelvedata", "ticker": "XAU/USD", "digits": 2},
    "BTCUSDT": {"label": "BTC/USDT", "source": "binance", "ticker": "BTCUSDT", "digits": 1},
    "ETHUSDT": {"label": "ETH/USDT", "source": "binance", "ticker": "ETHUSDT", "digits": 2},
    "SOLUSDT": {"label": "SOL/USDT", "source": "binance", "ticker": "SOLUSDT", "digits": 2},
    "SUIUSDT": {"label": "SUI/USDT", "source": "binance", "ticker": "SUIUSDT", "digits": 4},
    "TAOUSDT": {"label": "TAO/USDT", "source": "binance", "ticker": "TAOUSDT", "digits": 2},
    "HYPEUSDT": {"label": "HYPE/USDT (Hyperliquid)", "source": "binance", "ticker": "HYPEUSDT", "digits": 3},
    "ONDOUSDT": {"label": "ONDO/USDT", "source": "binance", "ticker": "ONDOUSDT", "digits": 4},
    "ASTERUSDT": {"label": "ASTER/USDT", "source": "binance", "ticker": "ASTERUSDT", "digits": 4},
}

# Jadwal (jam WIB)
JAM_LAPORAN_PAGI = (7, 0)
JAM_UPDATE_INTRADAY = [(11, 0), (15, 0), (19, 0), (23, 0)]
SCALP_JAM_MULAI = 14   # sesi London
SCALP_JAM_SELESAI = 24  # sampai tengah malam (sesi New York)
SCALP_TIAP_MENIT = 15
