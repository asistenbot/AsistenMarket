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
from scalper import cari_setup, cari_setup_v2, cari_setup_dengan

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


# Biaya bolak-balik (buka + tutup) dalam % harga. Crypto: fee taker futures ~0.05% x2. Emas: spread.
BIAYA_PCT = {"binance": 0.10, "twelvedata": 0.02}


def strategi_standar():
    return {
        "lama": lambda a, b, c, d, dg: cari_setup(a, b, c, dg),
        "v2 skor≥3": lambda a, b, c, d, dg: cari_setup_v2(a, b, c, d, dg, 3),
        "v2 skor≥5": lambda a, b, c, d, dg: cari_setup_v2(a, b, c, d, dg, 5),
    }


async def uji_symbol(symbol: str, hari: int = 30, strategi: dict | None = None,
                     jam_mulai: int | None = None, jam_selesai: int | None = None) -> dict:
    strategi = strategi or strategi_standar()
    c5 = await history(symbol, "5m", hari * 288 + 400)
    c15 = await history(symbol, "15m", hari * 96 + 400)
    c1h = await history(symbol, "1h", hari * 24 + 400)
    c4h = await history(symbol, "4h", hari * 6 + 400)
    t15, t1h, t4h = ([c["t"] for c in x] for x in (c15, c1h, c4h))
    digits = config.SYMBOLS[symbol]["digits"]
    biaya = BIAYA_PCT[config.SYMBOLS[symbol]["source"]]
    jm = config.SCALP_JAM_MULAI if jam_mulai is None else jam_mulai
    js = config.SCALP_JAM_SELESAI if jam_selesai is None else jam_selesai

    hasil = {k: [] for k in strategi}
    sibuk = {k: -1 for k in strategi}
    for i in range(300, len(c5) - 1, 3):  # tiap 15 menit
        sekarang = c5[i]["t"] + timedelta(minutes=5)
        jam_wib = (sekarang + timedelta(hours=7)).hour
        if not (jm <= jam_wib < js):
            continue
        if all(i <= b for b in sibuk.values()):
            continue
        s5 = c5[max(0, i - 299):i + 1] + [c5[i]]
        s15 = _potong(c15, t15, sekarang, 15)
        s1h = _potong(c1h, t1h, sekarang, 60)
        s4h = _potong(c4h, t4h, sekarang, 240, 150)
        if len(s15) < 61 or len(s1h) < 61:
            continue
        cache = {}
        for nama, fn in strategi.items():
            if i <= sibuk[nama]:
                continue
            s = fn(s5, s15, s1h, s4h, digits)
            if not s:
                continue
            key = (s["arah"], s["entry"], s["sl"])
            if key not in cache:
                cache[key] = _hasil(s, c5[i + 1:])
            h, durasi = cache[key]
            if not h:
                continue
            sibuk[nama] = i + durasi
            risk_pct = s["risk_poin"] / s["entry"] * 100 if s["entry"] else 1
            biaya_r = biaya / risk_pct if risk_pct else 0
            hasil[nama].append({"hasil": h, "r": R_HASIL[h], "r_net": R_HASIL[h] - biaya_r,
                                "skor": s.get("skor"), "waktu": sekarang.isoformat()})
        if i % 300 == 0:
            await asyncio.sleep(0)
    return hasil


def statistik(trades: list) -> dict:
    n = len(trades)
    menang = sum(1 for t in trades if t["hasil"] in ("tp1", "tp2"))
    kalah = sum(1 for t in trades if t["hasil"] == "sl")
    total_r = sum(t["r"] for t in trades)
    net = [t.get("r_net", t["r"]) for t in trades]
    untung = sum(x for x in net if x > 0)
    rugi = -sum(x for x in net if x < 0)
    return {
        "n": n, "menang": menang, "kalah": kalah,
        "wr": menang / (menang + kalah) * 100 if menang + kalah else 0,
        "total_r": total_r, "rata_r": total_r / n if n else 0,
        "net_r": sum(net), "rata_net": sum(net) / n if n else 0,
        "pf": untung / rugi if rugi else (float("inf") if untung else 0),
    }


def _baris(nama: str, st: dict) -> str:
    pf = "∞" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
    return (f"{nama}: {st['n']} sinyal | WR {st['wr']:.0f}% | kotor {st['total_r']:+.1f}R | "
            f"bersih {st['net_r']:+.1f}R ({st['rata_net']:+.2f}R/sinyal) | PF {pf}")


async def uji_semua(hari: int = 30, symbols=None, strategi: dict | None = None) -> tuple:
    """Return (teks laporan, data mentah)."""
    strategi = strategi or strategi_standar()
    semua = {k: [] for k in strategi}
    per_koin = {}
    gagal = []
    for sym in symbols or config.SYMBOLS:
        try:
            h = await uji_symbol(sym, hari, strategi)
        except Exception as e:
            logger.warning("Backtest %s gagal: %s", sym, e)
            gagal.append(sym)
            continue
        per_koin[sym] = h
        for k in strategi:
            semua[k] += h[k]

    baris = [f"🧪 BACKTEST SCALPING {hari} HARI (jam {config.SCALP_JAM_MULAI}:00–{config.SCALP_JAM_SELESAI}:00 WIB)",
             "Sudah dipotong biaya: crypto 0.1%, emas 0.02% per transaksi.", ""]
    for k in strategi:
        baris.append(_baris(k, statistik(semua[k])))
    baris.append("")
    pertama = list(strategi)[0]
    baris.append(f"Per koin ({pertama}, bersih):")
    for sym, h in per_koin.items():
        st = statistik(h[pertama])
        nama = config.SYMBOLS[sym]["label"].split(" ")[0]
        baris.append(f"• {nama}: {st['n']} sinyal, WR {st['wr']:.0f}%, {st['net_r']:+.1f}R")
    if gagal:
        baris.append(f"\nGagal ambil data: {', '.join(gagal)}")
    baris.append("\nR = kelipatan risiko. PF = total untung ÷ total rugi (di atas 1 = untung).")
    baris.append("Hasil masa lalu bukan jaminan ke depan.")
    return "\n".join(baris), {"semua": semua, "per_koin": per_koin}


def strategi_eksperimen():
    s = {"lama": cari_setup_dengan([])}
    for f in ("candle", "tidak_jauh", "volatilitas", "adx", "4h", "volume", "vwap", "ruang", "rsi", "risk_min"):
        s[f"+{f}"] = cari_setup_dengan([f])
    s["v2 skor≥3"] = lambda a, b, c, d, dg: cari_setup_v2(a, b, c, d, dg, 3)
    return s
