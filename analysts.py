"""Analis swing & intraday: kumpulkan ringkasan teknikal per timeframe."""
import logging

import config
from data import get_candles
from indicators import summarize

logger = logging.getLogger(__name__)

TF_SWING = ["3M", "1M", "1w", "1d"]
TF_INTRADAY = ["4h", "1h", "15m"]

NAMA_TF = {"3M": "3 Bulan", "1M": "Bulanan", "1w": "Mingguan", "1d": "Harian",
           "4h": "4 Jam", "1h": "1 Jam", "15m": "15 Menit", "5m": "5 Menit"}


async def analisa(symbol: str, tfs: list) -> dict:
    digits = config.SYMBOLS[symbol]["digits"]
    hasil = {}
    for tf in tfs:
        try:
            candles = await get_candles(symbol, tf, 300 if tf not in ("1M", "3M") else 120)
            hasil[tf] = summarize(candles, digits)
        except Exception as e:
            logger.warning("Analisa %s %s gagal: %s", symbol, tf, e)
            hasil[tf] = {"error": str(e)}
    return hasil


async def analis_swing(symbol: str) -> dict:
    return await analisa(symbol, TF_SWING)


async def analis_intraday(symbol: str) -> dict:
    return await analisa(symbol, TF_INTRADAY)
