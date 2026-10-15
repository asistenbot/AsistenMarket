"""Backtest scalper: jalankan strategi ke data historis asli, bandingkan versi lama vs versi 2.

Cara kerja: maju candle 5m demi candle 5m (dicek tiap 15 menit, sama kayak bot live),
pakai cuma data yang sudah ada di waktu itu (nggak ngintip masa depan), lalu simulasi hasil
sinyal dengan aturan yang sama dengan pencatat (SL duluan kalau satu candle kena dua-duanya,
setelah TP1 SL pindah ke entry, maksimal 24 jam).
"""
import asyncio
import bisect
import logging
from datetime import datetime, timedelta, timezone

import httpx

import config
from data import BINANCE_TF, TWELVE_TF, _candle, _ms, pasar_buka  # noqa: F401
from scalper import cari_setup, cari_setup_v2

logger = logging.getLogger(__name__)

TF_MENIT = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
R_HASIL = {"tp2": 2.5, "tp1": 1.5, "sl": -1.0, "expired": 0.0}


# ---------- ambil data panjang ----------
async def _history_binance(ticker: str, tf: str, n: int) -> list:
    out, end = [], None
    async with httpx.AsyncClient(timeout=30) as client:
        while len(out) < n:
            params = {"symbol": ticker, "interval": BINANCE_TF[tf], "limit": 1000}
            if end:
                params["endTime"] = end
            last_err = None
            for host in ("https://api.binance.com", "https://data-api.binance.vision"):
                try:
                    r = await client.get(f"{host}/api/v3/klines", params=params)
                    r.raise_for_status()
                    rows = r.json()
                    break
                except Exception as e:
                    last_err, rows = e, None
            if rows is None:
                raise RuntimeError(f"Binance {ticker} {tf}: {last_err}")
            if not rows:
                break
            out = [_candle(_ms(k[0]), k[1], k[2], k[3], k[4], k[5]) for k in rows] + out
            end = rows[0][0] - 1
            if len(rows) < 1000:
                break
            await asyncio.sleep(0.2)
    return out[-n:]


async def _history_twelvedata(ticker: str, tf: str, n: int) -> list:
    params = {"symbol": ticker, "interval": TWELVE_TF[tf], "outputsize": min(n, 5000),
              "timezone": "UTC", "apikey": config.TWELVEDATA_API_KEY}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get("https://api.twelvedata.com/time_series", params=params)
    d = r.json()
    if d.get("status") != "ok":
        raise RuntimeError(f"TwelveData {ticker} {tf}: {d.get('message', d)}")
    await asyncio.sleep(8)  # jaga kuota 8 request/menit
    return [_candle(datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc),
                    v["open"], v["high"], v["low"], v["close"], v.get("volume", 0))
            for v in reversed(d["values"])]


async def history(symbol: str, tf: str, n: int) -> list:
    info = config.SYMBOLS[symbol]
    if info["source"] == "binance":
        return await _history_binance(info["ticker"], tf, n)
    return await _history_twelvedata(info["ticker"], tf, n)


# ---------- simulasi ----------
def _hasil(s: dict, ke_depan: list) -> tuple:
    buy = s["arah"] == "BUY"
    tp1_kena = False
    for j, c in enumerate(ke_depan[:288]):  # 24 jam
        hi, lo = c["h"], c["l"]
        if not tp1_kena:
            if lo <= s["sl"] if buy else hi >= s["sl"]:
                return "sl", j
            if hi >= s["tp1"] if buy else lo <= s["tp1"]:
                tp1_kena = True
                if hi >= s["tp2"] if buy else lo <= s["tp2"]:
                    return "tp2", j
        else:
            if lo <= s["entry"] if buy else hi >= s["entry"]:
                return "tp1", j
            if hi >= s["tp2"] if buy else lo <= s["tp2"]:
                return "tp2", j
    if len(ke_depan) < 288:
        return None, None  # data ke depan belum cukup, jangan dihitung
    return ("tp1" if tp1_kena else "expired"), 288


def _potong(candles: list, waktu: list, sampai: datetime, menit: int, jumlah: int = 300) -> list:
    """Candle yang sudah selesai sebelum `sampai`, + 1 salinan candle terakhir
    (karena fungsi strategi membuang candle terakhir yang dianggap belum selesai)."""
    idx = bisect.bisect_right(waktu, sampai - timedelta(minutes=menit))
    tutup = candles[max(0, idx - jumlah):idx]
    return tutup + tutup[-1:] if tutup else []


async def uji_symbol(symbol: str, hari: int = 30, jam_mulai: int | None = None, jam_selesai: int | None = None) -> dict:
    n5 = hari * 288 + 400
    c5 = await history(symbol, "5m", n5)
    c15 = await history(symbol, "15m", hari * 96 + 400)
    c1h = await history(symbol, "1h", hari * 24 + 400)
    c4h = await history(symbol, "4h", hari * 6 + 400)
    t5, t15, t1h, t4h = ([c["t"] for c in x] for x in (c5, c15, c1h, c4h))
    digits = config.SYMBOLS[symbol]["digits"]
    jm = config.SCALP_JAM_MULAI if jam_mulai is None else jam_mulai
    js = config.SCALP_JAM_SELESAI if jam_selesai is None else jam_selesai

    hasil = {"lama": [], "v2": {m: [] for m in range(7)}}
    sibuk_lama = -1
    sibuk_v2 = {m: -1 for m in range(7)}
    for i in range(300, len(c5) - 1, 3):  # tiap 15 menit
        sekarang = c5[i]["t"] + timedelta(minutes=5)  # waktu candle i selesai
        jam_wib = (sekarang + timedelta(hours=7)).hour
        if not (jm <= jam_wib < js):
            continue
        s5 = c5[max(0, i - 299):i + 1] + [c5[i]]
        s15 = _potong(c15, t15, sekarang, 15)
        s1h = _potong(c1h, t1h, sekarang, 60)
        s4h = _potong(c4h, t4h, sekarang, 240, 150)
        if len(s15) < 61 or len(s1h) < 61:
            continue
        if i > sibuk_lama:
            s = cari_setup(s5, s15, s1h, digits)
            if s:
                h, durasi = _hasil(s, c5[i + 1:])
                if h:
                    sibuk_lama = i + durasi
                    hasil["lama"].append({"hasil": h, "r": R_HASIL[h], "waktu": sekarang.isoformat()})
        if any(i > b for b in sibuk_v2.values()):
            s = cari_setup_v2(s5, s15, s1h, s4h, digits, skor_min=0)
            if s:
                h, durasi = _hasil(s, c5[i + 1:])
                if h:
                    for m in range(7):
                        if s["skor"] >= m and i > sibuk_v2[m]:
                            sibuk_v2[m] = i + durasi
                            hasil["v2"][m].append({"hasil": h, "r": R_HASIL[h], "skor": s["skor"],
                                                   "waktu": sekarang.isoformat()})
        if i % 300 == 0:
            await asyncio.sleep(0)  # kasih napas ke bot biar tetap responsif
    return hasil


def statistik(trades: list) -> dict:
    n = len(trades)
    menang = sum(1 for t in trades if t["hasil"] in ("tp1", "tp2"))
    kalah = sum(1 for t in trades if t["hasil"] == "sl")
    total_r = sum(t["r"] for t in trades)
    untung = sum(t["r"] for t in trades if t["r"] > 0)
    rugi = -sum(t["r"] for t in trades if t["r"] < 0)
    return {
        "n": n, "menang": menang, "kalah": kalah,
        "wr": menang / (menang + kalah) * 100 if menang + kalah else 0,
        "total_r": total_r, "rata_r": total_r / n if n else 0,
        "pf": untung / rugi if rugi else (float("inf") if untung else 0),
    }


def _baris(nama: str, st: dict) -> str:
    pf = "∞" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
    return (f"{nama}: {st['n']} sinyal | WR {st['wr']:.0f}% | total {st['total_r']:+.1f}R | "
            f"rata2 {st['rata_r']:+.2f}R/sinyal | PF {pf}")


async def uji_semua(hari: int = 30, symbols=None) -> tuple:
    """Return (teks laporan, data mentah)."""
    semua = {"lama": [], "v2": {m: [] for m in range(7)}}
    per_koin = {}
    gagal = []
    for sym in symbols or config.SYMBOLS:
        try:
            h = await uji_symbol(sym, hari)
        except Exception as e:
            logger.warning("Backtest %s gagal: %s", sym, e)
            gagal.append(sym)
            continue
        per_koin[sym] = h
        semua["lama"] += h["lama"]
        for m in range(7):
            semua["v2"][m] += h["v2"][m]
        logger.info("BACKTEST %s: lama %s | v2>=3 %s", sym, statistik(h["lama"]), statistik(h["v2"][3]))

    baris = [f"🧪 BACKTEST SCALPING {hari} HARI (jam {config.SCALP_JAM_MULAI}:00–{config.SCALP_JAM_SELESAI}:00 WIB)", ""]
    baris.append(_baris("Versi lama", statistik(semua["lama"])))
    baris.append("")
    baris.append("Versi 2 berdasarkan skor minimal:")
    for m in range(7):
        if semua["v2"][m]:
            baris.append("  " + _baris(f"skor ≥{m}", statistik(semua["v2"][m])))
    baris.append("")
    baris.append("Per koin (lama → v2 skor ≥3):")
    for sym, h in per_koin.items():
        a, b = statistik(h["lama"]), statistik(h["v2"][3])
        nama = config.SYMBOLS[sym]["label"].split(" ")[0]
        baris.append(f"• {nama}: {a['n']} sinyal {a['total_r']:+.1f}R → {b['n']} sinyal {b['total_r']:+.1f}R")
    if gagal:
        baris.append(f"\nGagal ambil data: {', '.join(gagal)}")
    baris.append("\nPF (profit factor) = total untung ÷ total rugi. Di atas 1 = untung, makin tinggi makin bagus.")
    baris.append("Hasil masa lalu bukan jaminan ke depan, spread & slippage broker belum dihitung.")
    return "\n".join(baris), {"semua": semua, "per_koin": per_koin}
