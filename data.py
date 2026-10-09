"""Kurir data: ambil candle dari Binance (crypto) dan TwelveData (emas)."""
import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

import config

logger = logging.getLogger(__name__)

# Timeframe internal -> kode di masing-masing sumber
BINANCE_TF = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w", "1M": "1M"}
TWELVE_TF = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1day", "1w": "1week", "1M": "1month"}

# Berapa lama data disimpan sebelum diambil ulang (detik) — hemat kuota TwelveData
CACHE_TTL = {"5m": 60, "15m": 120, "1h": 300, "4h": 900, "1d": 1800, "1w": 3600, "1M": 3600}

BINANCE_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]

_cache: dict = {}
_td_lock = asyncio.Lock()
_td_last_call = 0.0
TD_JEDA_DETIK = 8  # kuota gratis TwelveData: 8 request per menit


class DataError(Exception):
    pass


def _candle(t, o, h, l, c, v=0.0):
    return {"t": t, "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v or 0)}


OKX_TF = {"5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1Dutc", "1w": "1Wutc", "1M": "1Mutc"}
BYBIT_TF = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D", "1w": "W", "1M": "M"}

# Sumber yang terakhir berhasil per ticker, biar nggak coba dari awal terus
_sumber_ok: dict = {}


def _ms(x) -> datetime:
    return datetime.fromtimestamp(int(x) / 1000, tz=timezone.utc)


async def _src_binance_spot(client, ticker, tf, limit):
    last = None
    for host in BINANCE_HOSTS:
        try:
            r = await client.get(f"{host}/api/v3/klines",
                                 params={"symbol": ticker, "interval": BINANCE_TF[tf], "limit": min(limit, 1000)})
            r.raise_for_status()
            return [_candle(_ms(k[0]), k[1], k[2], k[3], k[4], k[5]) for k in r.json()]
        except Exception as e:
            last = e
    raise DataError(f"binance spot: {last}")


async def _src_binance_futures(client, ticker, tf, limit):
    r = await client.get("https://fapi.binance.com/fapi/v1/klines",
                         params={"symbol": ticker, "interval": BINANCE_TF[tf], "limit": min(limit, 1500)})
    r.raise_for_status()
    return [_candle(_ms(k[0]), k[1], k[2], k[3], k[4], k[5]) for k in r.json()]


async def _src_okx(client, ticker, tf, limit):
    inst = ticker.replace("USDT", "-USDT")
    r = await client.get("https://www.okx.com/api/v5/market/candles",
                         params={"instId": inst, "bar": OKX_TF[tf], "limit": min(limit, 300)})
    r.raise_for_status()
    d = r.json()
    if d.get("code") != "0" or not d.get("data"):
        raise DataError(f"okx: {d.get('msg') or 'kosong'}")
    return [_candle(_ms(k[0]), k[1], k[2], k[3], k[4], k[5]) for k in reversed(d["data"])]


async def _src_bybit(client, ticker, tf, limit):
    r = await client.get("https://api.bybit.com/v5/market/kline",
                         params={"category": "spot", "symbol": ticker, "interval": BYBIT_TF[tf],
                                 "limit": min(limit, 1000)})
    r.raise_for_status()
    d = r.json()
    rows = (d.get("result") or {}).get("list") or []
    if d.get("retCode") != 0 or not rows:
        raise DataError(f"bybit: {d.get('retMsg') or 'kosong'}")
    return [_candle(_ms(k[0]), k[1], k[2], k[3], k[4], k[5]) for k in reversed(rows)]


_SUMBER_CRYPTO = [
    ("binance", _src_binance_spot),
    ("binance-futures", _src_binance_futures),
    ("okx", _src_okx),
    ("bybit", _src_bybit),
]


async def _fetch_binance(ticker: str, tf: str, limit: int) -> list:
    """Ambil candle crypto. Coba Binance dulu, kalau koin nggak ada/gagal pindah ke sumber cadangan."""
    urutan = sorted(_SUMBER_CRYPTO, key=lambda s: s[0] != _sumber_ok.get(ticker))
    errors = []
    async with httpx.AsyncClient(timeout=20) as client:
        for nama, fn in urutan:
            try:
                candles = await fn(client, ticker, tf, limit)
                if len(candles) >= 5:
                    if _sumber_ok.get(ticker) != nama:
                        logger.info("Data %s diambil dari %s", ticker, nama)
                    _sumber_ok[ticker] = nama
                    return candles
                errors.append(f"{nama}: data sedikit")
            except Exception as e:
                errors.append(f"{nama}: {str(e)[:80]}")
    raise DataError(f"Gagal ambil {ticker} {tf} ({'; '.join(errors)})")


async def _fetch_twelvedata(ticker: str, tf: str, limit: int) -> list:
    global _td_last_call
    if not config.TWELVEDATA_API_KEY:
        raise DataError("TWELVEDATA_API_KEY belum diisi")
    params = {
        "symbol": ticker,
        "interval": TWELVE_TF[tf],
        "outputsize": limit,
        "timezone": "UTC",
        "apikey": config.TWELVEDATA_API_KEY,
    }
    async with _td_lock:
        tunggu = TD_JEDA_DETIK - (time.monotonic() - _td_last_call)
        if tunggu > 0:
            await asyncio.sleep(tunggu)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get("https://api.twelvedata.com/time_series", params=params)
        finally:
            _td_last_call = time.monotonic()
    data = r.json()
    if data.get("status") != "ok":
        raise DataError(f"TwelveData {ticker} {tf}: {data.get('message', data)}")
    rows = list(reversed(data.get("values", [])))  # TwelveData kirim yang terbaru duluan
    out = []
    for v in rows:
        t = datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc)
        out.append(_candle(t, v["open"], v["high"], v["low"], v["close"], v.get("volume", 0)))
    return out


def _to_quarter(candles: list) -> list:
    """Gabungkan candle bulanan jadi candle 3 bulanan (kuartal)."""
    groups: dict = {}
    for c in candles:
        key = (c["t"].year, (c["t"].month - 1) // 3)
        groups.setdefault(key, []).append(c)
    out = []
    for key in sorted(groups):
        g = groups[key]
        out.append(_candle(g[0]["t"], g[0]["o"], max(x["h"] for x in g), min(x["l"] for x in g), g[-1]["c"],
                           sum(x["v"] for x in g)))
    return out


async def get_candles(symbol: str, tf: str, limit: int = 250) -> list:
    """Ambil candle untuk symbol & timeframe (5m, 15m, 1h, 4h, 1d, 1w, 1M, 3M)."""
    if tf == "3M":
        monthly = await get_candles(symbol, "1M", 120)
        return _to_quarter(monthly)

    info = config.SYMBOLS[symbol]
    key = (symbol, tf, limit)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL.get(tf, 300):
        return hit[1]

    if info["source"] == "binance":
        candles = await _fetch_binance(info["ticker"], tf, limit)
    else:
        candles = await _fetch_twelvedata(info["ticker"], tf, min(limit, 5000))

    if len(candles) < 5:
        raise DataError(f"Data {symbol} {tf} terlalu sedikit")
    _cache[key] = (time.monotonic(), candles)
    return candles


def pasar_emas_buka(now_utc: datetime | None = None) -> bool:
    """Emas libur dari Jumat malam (sekitar 21:00 UTC) sampai Minggu malam (sekitar 22:00 UTC)."""
    now = now_utc or datetime.now(timezone.utc)
    wd, h = now.weekday(), now.hour  # Senin=0
    if wd == 5:
        return False
    if wd == 4 and h >= 21:
        return False
    if wd == 6 and h < 22:
        return False
    return True


def pasar_buka(symbol: str) -> bool:
    if config.SYMBOLS[symbol]["source"] == "twelvedata":
        return pasar_emas_buka()
    return True
