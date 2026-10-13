"""Sniper entry: rencana limit order di zona penting 1H, searah trend 4H/1D, RR minimal 1:3.

Alur satu rencana:
  menunggu  → harga belum sampai zona (alarm sekali waktu harga mendekat)
  aktif     → limit order kena (harga nyentuh entry), sekarang dipantau TP/SL
  selesai   → kena TP, kena SL, batal (harga lari ke TP duluan / zona jebol), atau kedaluwarsa
Murni hitungan, tanpa AI.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import config
from indicators import atr, pivots, summarize

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/data")
FILE = os.path.join(DATA_DIR, "sniper.json")

RR_MIN = 3.0
RR_MAKS = 6.0  # TP dibatasi maksimal 1:6
JAM_MENUNGGU = 48   # rencana yang belum kena entry setelah 48 jam dibatalkan
JAM_AKTIF = 72      # posisi yang belum kena TP/SL setelah 72 jam ditutup di harga terakhir


# ---------- cari rencana ----------
def _mirror(candles: list) -> list:
    """Balik harga (dikali -1) supaya logika SELL bisa pakai logika BUY."""
    return [{"t": c["t"], "o": -c["o"], "h": -c["l"], "l": -c["h"], "c": -c["c"], "v": c["v"]} for c in candles]


def _zona_demand(c: list, a: float, harga: float):
    """Cari zona beli terdekat di bawah harga: order block dulu, kalau nggak ada pakai support swing."""
    n = len(c)
    kandidat = []
    for i in range(max(0, n - 160), n - 4):
        k = c[i]
        if k["c"] >= k["o"]:
            continue  # order block = candle merah terakhir sebelum harga terbang
        if not any(c[j]["c"] > k["h"] + 1.0 * a for j in range(i + 1, min(i + 4, n))):
            continue
        top, bot = k["o"], k["l"]
        if any(c[j]["l"] <= top for j in range(i + 4, n)):
            continue  # zona sudah pernah disentuh lagi (sudah "dipakai")
        bot = max(bot, top - 1.5 * a)
        bot = min(bot, top - 0.2 * a)
        kandidat.append(("Order block 1H", bot, top))

    if not kandidat:
        highs, lows = pivots(c[-160:])
        for pl in lows:
            idx = max(j for j in range(n) if c[j]["l"] == pl) if any(x["l"] == pl for x in c) else None
            if idx is not None and any(x["c"] < pl for x in c[idx + 1:]):
                continue  # support sudah jebol
            kandidat.append(("Support swing 1H", pl - 0.1 * a, pl + 0.3 * a))

    kandidat = [z for z in kandidat if z[2] < harga - 0.2 * a]
    if not kandidat:
        return None
    return max(kandidat, key=lambda z: z[2])  # yang paling dekat dengan harga


def _rencana_buy(c1h: list, c4h: list, harga: float):
    a1 = atr(c1h)
    a4 = atr(c4h)
    if not a1 or not a4:
        return None
    zona = _zona_demand(c1h, a1, harga)
    if not zona:
        return None
    jenis, bot, top = zona
    if harga - top > 3 * a4:
        return None  # zona terlalu jauh, nggak relevan hari-hari ini
    entry = top
    sl = bot - 0.25 * a1
    risk = entry - sl
    if risk <= 0:
        return None
    h1, _ = pivots(c1h[-200:])
    h4, _ = pivots(c4h[-150:])
    batas = entry + 4 * a4  # TP maksimal sekitar 4x gerakan rata-rata 4 jam, biar realistis
    level = sorted({x for x in h1 + h4 + [max(k["h"] for k in c1h[-100:])] if harga < x <= batas})
    for lv in level:
        tp = lv - 0.1 * a1  # sedikit di depan resistance biar lebih gampang kena
        if tp <= harga + 0.5 * a1:
            continue  # TP harus jelas di atas harga sekarang
        rr = (tp - entry) / risk
        if rr > RR_MAKS:
            tp, rr = entry + RR_MAKS * risk, RR_MAKS
            if tp <= harga + 0.5 * a1:
                return None  # zona terlalu jauh di bawah harga, TP realistisnya malah di bawah harga sekarang
        if rr >= RR_MIN:
            return {"jenis": jenis, "zona_bawah": bot, "zona_atas": top, "entry": entry, "sl": sl, "tp": tp,
                    "rr": rr, "dekat": entry + 0.3 * a1}
    return None


def _bias(c4h: list, c1d: list) -> str | None:
    t4 = summarize(c4h)["trend"]
    t1d = summarize(c1d)["trend"]
    if t4 == "naik" and t1d != "turun":
        return "BUY"
    if t4 == "turun" and t1d != "naik":
        return "SELL"
    if t4 == "sideways" and t1d in ("naik", "turun"):
        return "BUY" if t1d == "naik" else "SELL"
    return None


def cari_rencana(symbol: str, c1h: list, c4h: list, c1d: list) -> dict | None:
    digits = config.SYMBOLS[symbol]["digits"]
    c1h, c4h, c1d = c1h[:-1], c4h[:-1], c1d  # buang candle 1H/4H yang belum selesai
    if len(c1h) < 100 or len(c4h) < 60 or len(c1d) < 30:
        return None
    arah = _bias(c4h, c1d)
    if not arah:
        return None
    harga = c1h[-1]["c"]
    if arah == "BUY":
        p = _rencana_buy(c1h, c4h, harga)
    else:
        p = _rencana_buy(_mirror(c1h), _mirror(c4h), -harga)
        if p:
            p = {k: (-v if isinstance(v, float) and k != "rr" else v) for k, v in p.items()}
            p["zona_bawah"], p["zona_atas"] = p["zona_atas"], p["zona_bawah"]
    if not p:
        return None
    rd = lambda x: round(x, digits)  # noqa: E731
    return {
        "symbol": symbol, "arah": arah, "jenis": p["jenis"],
        "zona_bawah": rd(p["zona_bawah"]), "zona_atas": rd(p["zona_atas"]),
        "entry": rd(p["entry"]), "sl": rd(p["sl"]), "tp": rd(p["tp"]), "dekat": rd(p["dekat"]),
        "rr": round(p["rr"], 1), "harga": rd(harga),
        "trend_4h": summarize(c4h)["trend"], "trend_1d": summarize(c1d)["trend"],
    }


# ---------- simpan & pantau ----------
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


def simpan(r: dict) -> bool:
    """Simpan rencana baru. Rencana lama yang masih menunggu untuk koin yang sama diganti.
    Return False kalau rencananya sama persis dengan yang sudah ada, atau koin ini lagi punya posisi aktif."""
    rows = _load()
    for x in rows:
        if x["symbol"] != r["symbol"]:
            continue
        if x["status"] == "aktif":
            return False
        if x["status"] == "menunggu":
            if x["arah"] == r["arah"] and x["entry"] == r["entry"] and x["sl"] == r["sl"]:
                return False
            x["status"] = "selesai"
            x["hasil"] = "diganti"
            x["selesai"] = datetime.now(timezone.utc).isoformat()
    rows.append(dict(r, id=uuid.uuid4().hex[:8], status="menunggu", alarm_dekat=False,
                     dibuat=datetime.now(timezone.utc).isoformat(), masuk=None, hasil=None, selesai=None))
    _save(rows)
    return True


def daftar_aktif() -> list:
    return [x for x in _load() if x["status"] in ("menunggu", "aktif")]


def _nama(sym: str) -> str:
    return config.SYMBOLS.get(sym, {}).get("label", sym)


def _tutup(x: dict, hasil: str, r_val: float | None = None):
    x["status"] = "selesai"
    x["hasil"] = hasil
    x["selesai"] = datetime.now(timezone.utc).isoformat()
    if r_val is not None:
        x["r"] = round(r_val, 2)


def _proses(x: dict, candles: list) -> list:
    """Jalan candle 5m sejak rencana dibuat. Return list pesan yang perlu dikirim."""
    pesan = []
    buy = x["arah"] == "BUY"
    nama = _nama(x["symbol"])
    mulai = datetime.fromisoformat(x["masuk"] or x["dibuat"])
    now = datetime.now(timezone.utc)
    for c in candles:
        if c["t"] < mulai:
            continue
        if x["status"] == "aktif" and c["t"] <= datetime.fromisoformat(x["masuk"]):
            continue  # candle tempat entry kena sudah dicek SL-nya
        hi, lo = c["h"], c["l"]
        if x["status"] == "menunggu":
            kena_entry = lo <= x["entry"] if buy else hi >= x["entry"]
            lari_tp = hi >= x["tp"] if buy else lo <= x["tp"]
            if lari_tp and not kena_entry:
                _tutup(x, "batal")
                pesan.append(f"🚫 SNIPER {x['arah']} {nama} batal: harga udah lari ke TP sebelum kena entry.")
                return pesan
            if not x["alarm_dekat"] and (lo <= x["dekat"] if buy else hi >= x["dekat"]) and not kena_entry:
                x["alarm_dekat"] = True
                pesan.append(f"⚠️ SNIPER {x['arah']} {nama}: harga mendekati zona!\n"
                             f"Entry {x['entry']} | SL {x['sl']} | TP {x['tp']} (1:{x['rr']})\n"
                             "Siapin limit order kalau belum dipasang.")
            if kena_entry:
                x["status"] = "aktif"
                x["masuk"] = c["t"].isoformat()
                pesan.append(f"🎯 SNIPER {x['arah']} {nama}: limit KENA di {x['entry']}\n"
                             f"SL {x['sl']} | TP {x['tp']}. Sekarang tinggal sabar.")
                if lo <= x["sl"] if buy else hi >= x["sl"]:
                    _tutup(x, "sl", -1.0)
                    pesan.append(f"❌ SNIPER {nama} kena SL di candle yang sama. Hasil: -1R")
                    return pesan
                continue
        else:  # aktif
            kena_sl = lo <= x["sl"] if buy else hi >= x["sl"]
            kena_tp = hi >= x["tp"] if buy else lo <= x["tp"]
            if kena_sl:
                _tutup(x, "sl", -1.0)
                pesan.append(f"❌ SNIPER {x['arah']} {nama} kena SL. Hasil: -1R")
                return pesan
            if kena_tp:
                _tutup(x, "tp", x["rr"])
                pesan.append(f"💰 SNIPER {x['arah']} {nama} kena TP {x['tp']}! Hasil: +{x['rr']}R")
                return pesan

    if x["status"] == "menunggu" and now - datetime.fromisoformat(x["dibuat"]) > timedelta(hours=JAM_MENUNGGU):
        _tutup(x, "kedaluwarsa")
        pesan.append(f"⌛ SNIPER {x['arah']} {nama} dibatalkan: 48 jam harga nggak sampai zona. Cabut limit order-nya.")
    elif x["status"] == "aktif" and now - datetime.fromisoformat(x["masuk"]) > timedelta(hours=JAM_AKTIF) and candles:
        last = candles[-1]["c"]
        risk = abs(x["entry"] - x["sl"])
        r_val = ((last - x["entry"]) if buy else (x["entry"] - last)) / risk if risk else 0
        _tutup(x, "ditutup", r_val)
        pesan.append(f"⌛ SNIPER {x['arah']} {nama} udah 72 jam belum kena TP/SL. "
                     f"Dihitung tutup di {round(last, config.SYMBOLS[x['symbol']]['digits'])} ({r_val:+.1f}R).")
    return pesan


async def pantau(get_candles, pasar_buka) -> list:
    rows = _load()
    pesan = []
    berubah = False
    for x in rows:
        if x["status"] not in ("menunggu", "aktif") or x["symbol"] not in config.SYMBOLS:
            continue
        if not pasar_buka(x["symbol"]):
            continue
        try:
            candles = await get_candles(x["symbol"], "5m", 300)
        except Exception as e:
            logger.warning("Pantau sniper %s gagal: %s", x["symbol"], e)
            continue
        sebelum = json.dumps(x, sort_keys=True, default=str)
        pesan += _proses(x, candles)
        berubah = berubah or json.dumps(x, sort_keys=True, default=str) != sebelum
    if berubah:
        _save(rows)
    return pesan


# ---------- tampilan ----------
def format_rencana(r: dict) -> str:
    nama = _nama(r["symbol"])
    ikon = "🟢" if r["arah"] == "BUY" else "🔴"
    jarak = abs(r["harga"] - r["entry"]) / r["harga"] * 100
    posisi = "di atas" if r["harga"] > r["entry"] else "di bawah"
    return (
        f"{ikon} SNIPER {'BUY' if r['arah'] == 'BUY' else 'SELL'} {nama}\n\n"
        f"Zona: {min(r['zona_bawah'], r['zona_atas'])} – {max(r['zona_bawah'], r['zona_atas'])} ({r['jenis']})\n"
        f"Limit {'buy' if r['arah'] == 'BUY' else 'sell'}: {r['entry']}\n"
        f"Stop loss: {r['sl']}\n"
        f"Take profit: {r['tp']}\n"
        f"Risk:Reward = 1:{r['rr']}\n\n"
        f"Harga sekarang {r['harga']} ({jarak:.2f}% {posisi} entry)\n"
        f"Trend 4H {r['trend_4h']}, 1D {r['trend_1d']}\n"
        "Pasang limit order, jangan kejar harga. Bot bakal kasih alarm waktu harga mendekat & waktu entry kena."
    )


def format_daftar() -> str:
    aktif = daftar_aktif()
    if not aktif:
        return "Belum ada rencana sniper yang jalan."
    baris = ["📋 RENCANA SNIPER YANG JALAN"]
    for x in aktif:
        st = "⏳ nunggu entry" if x["status"] == "menunggu" else "🎯 posisi aktif"
        baris.append(f"\n{_nama(x['symbol'])} {x['arah']} — {st}\n"
                     f"Entry {x['entry']} | SL {x['sl']} | TP {x['tp']} (1:{x['rr']})")
    return "\n".join(baris)


def rekap(hari: int = 7) -> str:
    batas = datetime.now(timezone.utc) - timedelta(days=hari)
    rows = [x for x in _load() if x["status"] == "selesai" and x.get("selesai")
            and datetime.fromisoformat(x["selesai"]) >= batas]
    masuk = [x for x in rows if x["hasil"] in ("tp", "sl", "ditutup")]
    tidak = [x for x in rows if x["hasil"] in ("batal", "kedaluwarsa")]
    if not masuk and not tidak:
        return "🎯 SNIPER: belum ada rencana yang selesai."
    tp = sum(1 for x in masuk if x["hasil"] == "tp")
    sl = sum(1 for x in masuk if x["hasil"] == "sl")
    total_r = sum(x.get("r", 0) for x in masuk)
    wr = tp / (tp + sl) * 100 if tp + sl else 0
    baris = [
        "🎯 SNIPER",
        f"Entry kena: {len(masuk)} | Nggak kena / batal: {len(tidak)}",
        f"💰 TP: {tp} | ❌ SL: {sl} | Win rate: {wr:.0f}%",
        f"Total: {total_r:+.1f}R",
    ]
    return "\n".join(baris)
