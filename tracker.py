"""Pencatat hasil ide scalping: simpan tiap sinyal, cek kena TP atau SL, bikin rekap.

Data disimpan di file JSON (DATA_DIR/sinyal.json). Di Railway, DATA_DIR = /data yang ditempel volume,
jadi catatan tidak hilang waktu bot restart.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import config

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/data")
FILE = os.path.join(DATA_DIR, "sinyal.json")
BATAS_JAM = 24  # sinyal yang belum kena TP/SL setelah 24 jam dianggap kedaluwarsa

# Hitungan R (kelipatan risiko): SL = -1R
R_HASIL = {"tp2": 2.5, "tp1": 1.5, "sl": -1.0, "expired": 0.0}
LABEL = {"tp2": "🎯 TP2", "tp1": "✅ TP1", "sl": "❌ SL", "expired": "⌛ Kedaluwarsa"}


def _load() -> list:
    try:
        with open(FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error("Gagal baca %s: %s", FILE, e)
        return []


def _save(rows: list):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rows, f)
        os.replace(tmp, FILE)
    except Exception as e:
        logger.error("Gagal simpan %s: %s", FILE, e)


def penyimpanan_permanen() -> bool:
    return os.path.ismount(DATA_DIR)


def catat(symbol: str, s: dict, sumber: str) -> bool:
    """Simpan sinyal baru. Return False kalau sinyal searah untuk koin ini masih terbuka (biar nggak dobel)."""
    rows = _load()
    for r in rows:
        if r["symbol"] == symbol and r["arah"] == s["arah"] and r["status"] == "open":
            return False
    rows.append({
        "id": uuid.uuid4().hex[:8],
        "symbol": symbol,
        "arah": s["arah"],
        "jenis": s["jenis"],
        "entry": s["entry"],
        "sl": s["sl"],
        "tp1": s["tp1"],
        "tp2": s["tp2"],
        "waktu": datetime.now(timezone.utc).isoformat(),
        "sumber": sumber,
        "status": "open",
        "tp1_kena": False,
        "hasil": None,
        "selesai": None,
    })
    _save(rows)
    return True


def _cek_satu(r: dict, candles: list) -> str | None:
    """Jalan candle demi candle setelah sinyal. Return hasil akhir atau None kalau masih jalan.

    Aturan (dibuat konservatif):
    - Kalau satu candle nyentuh SL dan TP1 sekaligus, dihitung SL.
    - Setelah TP1 kena, SL dianggap pindah ke entry (break even).
      Lalu kalau TP2 kena → tp2, kalau balik ke entry → tp1.
    """
    mulai = datetime.fromisoformat(r["waktu"])
    buy = r["arah"] == "BUY"
    for c in candles:
        if c["t"] < mulai:
            continue
        hi, lo = c["h"], c["l"]
        if not r["tp1_kena"]:
            kena_sl = lo <= r["sl"] if buy else hi >= r["sl"]
            kena_tp1 = hi >= r["tp1"] if buy else lo <= r["tp1"]
            if kena_sl:
                return "sl"
            if kena_tp1:
                r["tp1_kena"] = True
                kena_tp2 = hi >= r["tp2"] if buy else lo <= r["tp2"]
                if kena_tp2:
                    return "tp2"
                continue
        else:
            kena_tp2 = hi >= r["tp2"] if buy else lo <= r["tp2"]
            balik_be = lo <= r["entry"] if buy else hi >= r["entry"]
            if balik_be:
                return "tp1"
            if kena_tp2:
                return "tp2"
    if datetime.now(timezone.utc) - mulai > timedelta(hours=BATAS_JAM):
        return "tp1" if r["tp1_kena"] else "expired"
    return None


async def cek_semua(get_candles) -> list:
    """Cek semua sinyal terbuka. Return list pesan untuk sinyal yang baru selesai."""
    rows = _load()
    terbuka = [r for r in rows if r["status"] == "open"]
    if not terbuka:
        return []
    pesan = []
    cache = {}
    for r in terbuka:
        sym = r["symbol"]
        if sym not in config.SYMBOLS:
            r["status"] = "closed"
            r["hasil"] = "expired"
            continue
        try:
            if sym not in cache:
                cache[sym] = await get_candles(sym, "5m", 300)
            hasil = _cek_satu(r, cache[sym])
        except Exception as e:
            logger.warning("Cek sinyal %s gagal: %s", sym, e)
            continue
        if hasil:
            r["status"] = "closed"
            r["hasil"] = hasil
            r["selesai"] = datetime.now(timezone.utc).isoformat()
            pesan.append(_format_hasil(r))
    _save(rows)
    return pesan


def _format_hasil(r: dict) -> str:
    label = config.SYMBOLS.get(r["symbol"], {}).get("label", r["symbol"])
    r_val = R_HASIL[r["hasil"]]
    tanda = f"{r_val:+.1f}R" if r_val else "0R"
    return (f"{LABEL[r['hasil']]} — {label} {r['arah']}\n"
            f"Entry {r['entry']} | SL {r['sl']} | TP1 {r['tp1']} | TP2 {r['tp2']}\n"
            f"Hasil: {tanda}")


def rekap(hari: int = 7) -> str:
    rows = _load()
    batas = datetime.now(timezone.utc) - timedelta(days=hari)
    selesai = [r for r in rows if r["status"] == "closed" and r.get("selesai")
               and datetime.fromisoformat(r["selesai"]) >= batas]
    terbuka = [r for r in rows if r["status"] == "open"]

    judul = f"📒 REKAP SCALPING {hari} HARI TERAKHIR"
    if not selesai:
        return (f"{judul}\n\nBelum ada sinyal yang selesai."
                + (f"\nMasih jalan: {len(terbuka)} sinyal." if terbuka else ""))

    def ringkas(daftar):
        n = {k: sum(1 for r in daftar if r["hasil"] == k) for k in R_HASIL}
        menang = n["tp1"] + n["tp2"]
        kalah = n["sl"]
        wr = menang / (menang + kalah) * 100 if menang + kalah else 0
        total_r = sum(R_HASIL[r["hasil"]] for r in daftar)
        return n, menang, kalah, wr, total_r

    n, menang, kalah, wr, total_r = ringkas(selesai)
    baris = [
        judul, "",
        f"Total selesai: {len(selesai)} sinyal",
        f"🎯 TP2: {n['tp2']} | ✅ TP1: {n['tp1']} | ❌ SL: {n['sl']} | ⌛ Kedaluwarsa: {n['expired']}",
        f"Win rate: {wr:.0f}% ({menang} menang, {kalah} kalah)",
        f"Total: {total_r:+.1f}R",
        "",
        "Per koin:",
    ]
    per_koin = {}
    for r in selesai:
        per_koin.setdefault(r["symbol"], []).append(r)
    urut = sorted(per_koin.items(), key=lambda kv: -sum(R_HASIL[r["hasil"]] for r in kv[1]))
    for sym, daftar in urut:
        _, m, k, w, tr = ringkas(daftar)
        nama = config.SYMBOLS.get(sym, {}).get("label", sym).split(" ")[0]
        baris.append(f"• {nama}: {len(daftar)} sinyal, {m}M/{k}K, WR {w:.0f}%, {tr:+.1f}R")
    if terbuka:
        baris.append(f"\nMasih jalan: {len(terbuka)} sinyal")
    baris.append("\nR = kelipatan risiko. 1R = jarak entry ke SL. "
                 "Contoh: risiko Rp100rb per trade, +5R artinya untung sekitar Rp500rb.")
    if len(selesai) < 30:
        baris.append("⚠️ Sampel masih sedikit, angka win rate belum bisa dipercaya penuh.")
    return "\n".join(baris)
