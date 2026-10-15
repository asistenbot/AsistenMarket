"""Scalper: cari setup entry di 5m, searah trend 15m & 1h. Murni hitungan, tanpa AI."""
from indicators import atr, ema, rsi, trend_label


def _bias(candles: list) -> str:
    closes = [c["c"] for c in candles]
    if len(closes) < 50:
        return "belum jelas"
    e20, e50 = ema(closes, 20), ema(closes, 50)
    e200 = ema(closes, 200)[-1] if len(closes) >= 200 else None
    return trend_label(closes[-1], e20[-1], e50[-1], e200, e20[-1] - e20[-4])


def cari_setup(c5: list, c15: list, c1h: list, digits: int = 2) -> dict | None:
    """Return satu ide scalping atau None kalau tidak ada setup bagus.

    Candle terakhir dianggap belum selesai, jadi dibuang.
    """
    c5, c15, c1h = c5[:-1], c15[:-1], c1h[:-1]
    if len(c5) < 60 or len(c15) < 60 or len(c1h) < 60:
        return None

    b15, b1h = _bias(c15), _bias(c1h)
    if b15 == b1h and b15 in ("naik", "turun"):
        arah = "BUY" if b15 == "naik" else "SELL"
    else:
        return None  # timeframe besar tidak kompak → jangan scalping

    closes = [c["c"] for c in c5]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    a = atr(c5)
    r = rsi(closes)
    if not a or r is None:
        return None
    last, prev = c5[-1], c5[-2]
    close = last["c"]
    jenis = None

    if arah == "BUY":
        pullback = min(last["l"], prev["l"]) <= e20[-1] + 0.1 * a
        pantul = last["c"] > last["o"] and close > e20[-1] and close > e50[-1]
        if pullback and pantul and 40 <= r <= 68:
            jenis = "Pullback ke EMA20, mantul naik"
        hi20 = max(c["h"] for c in c5[-21:-1])
        if not jenis and close > hi20 and last["c"] > last["o"] and r < 75:
            jenis = "Breakout high 20 candle"
        if not jenis:
            return None
        swing = min(c["l"] for c in c5[-6:])
        sl = min(swing - 0.2 * a, close - 0.6 * a)
        sl = max(sl, close - 2.0 * a)
        risk = close - sl
        tp1, tp2 = close + 1.5 * risk, close + 2.5 * risk
    else:
        pullback = max(last["h"], prev["h"]) >= e20[-1] - 0.1 * a
        pantul = last["c"] < last["o"] and close < e20[-1] and close < e50[-1]
        if pullback and pantul and 32 <= r <= 60:
            jenis = "Pullback ke EMA20, mantul turun"
        lo20 = min(c["l"] for c in c5[-21:-1])
        if not jenis and close < lo20 and last["c"] < last["o"] and r > 25:
            jenis = "Breakdown low 20 candle"
        if not jenis:
            return None
        swing = max(c["h"] for c in c5[-6:])
        sl = max(swing + 0.2 * a, close + 0.6 * a)
        sl = min(sl, close + 2.0 * a)
        risk = sl - close
        tp1, tp2 = close - 1.5 * risk, close - 2.5 * risk

    rd = lambda x: round(x, digits)  # noqa: E731
    return {
        "arah": arah,
        "jenis": jenis,
        "entry": rd(close),
        "sl": rd(sl),
        "tp1": rd(tp1),
        "tp2": rd(tp2),
        "risk_poin": rd(risk),
        "rsi5m": round(r, 1),
        "atr5m": rd(a),
        "trend_15m": b15,
        "trend_1h": b1h,
    }


# ======================================================================
# Versi 2: trigger sama, tapi pakai filter wajib + skor kualitas setup.
# ======================================================================
from indicators import adx, median, pivots, vwap_harian  # noqa: E402

SKOR_MIN = 3  # default; bisa diubah dari env SCALP_SKOR_MIN


def cari_setup_v2(c5: list, c15: list, c1h: list, c4h: list | None = None, digits: int = 2,
                  skor_min: int | None = None) -> dict | None:
    """Sama seperti cari_setup, ditambah:
    Wajib : candle sinyal kuat (badan besar, tutup dekat ujung), harga nggak kejauhan dari EMA50,
            volatilitas normal (nggak mati, nggak lagi spike berita).
    Skor  : ADX 15m >= 20, trend 4H searah, volume di atas rata-rata, posisi vs VWAP harian,
            masih ada ruang ke TP1 sebelum ketemu resistance/support 1H, RSI di zona sehat.
    """
    dasar = cari_setup(c5, c15, c1h, digits)
    if not dasar:
        return None
    skor_min = SKOR_MIN if skor_min is None else skor_min
    buy = dasar["arah"] == "BUY"
    c5x, c15x, c1hx = c5[:-1], c15[:-1], c1h[:-1]
    last = c5x[-1]
    a = dasar["atr5m"]
    close = last["c"]

    # --- filter wajib ---
    rng = last["h"] - last["l"]
    if rng <= 0:
        return None
    body = abs(last["c"] - last["o"])
    posisi_tutup = (last["c"] - last["l"]) / rng if buy else (last["h"] - last["c"]) / rng
    if body < 0.4 * rng or posisi_tutup < 0.65:
        return None  # candle sinyal lemah / banyak ekor
    e50 = ema([c["c"] for c in c5x], 50)[-1]
    if abs(close - e50) > 2.5 * a:
        return None  # udah kejauhan, rawan balik
    trs = [max(c5x[i]["h"] - c5x[i]["l"], abs(c5x[i]["h"] - c5x[i - 1]["c"]), abs(c5x[i]["l"] - c5x[i - 1]["c"]))
           for i in range(max(1, len(c5x) - 200), len(c5x))]
    med = median(trs)
    if med > 0 and not (0.6 <= a / med <= 2.5):
        return None  # pasar terlalu sepi atau lagi meledak (berita)

    # --- skor kualitas ---
    skor, maks, alasan = 0, 0, []

    maks += 1
    ad = adx(c15x[-120:])
    if ad is not None and ad >= 20:
        skor += 1
        alasan.append(f"trend 15m kuat (ADX {ad:.0f})")

    if c4h:
        maks += 1
        b4 = _bias(c4h[:-1])
        if b4 == ("naik" if buy else "turun"):
            skor += 1
            alasan.append("searah trend 4H")

    vols = [c["v"] for c in c5x[-21:-1]]
    if sum(vols) > 0:
        maks += 1
        if last["v"] >= 1.2 * (sum(vols) / len(vols)):
            skor += 1
            alasan.append("volume naik")
        maks += 1
        vw = vwap_harian(c5x)
        if vw is not None and ((close > vw) if buy else (close < vw)):
            skor += 1
            alasan.append("di sisi benar VWAP")

    maks += 1
    highs, lows = pivots(c1hx[-120:])
    jarak_tp1 = abs(dasar["tp1"] - dasar["entry"])
    if buy:
        hambatan = [h for h in highs if h > close]
        ruang = (min(hambatan) - close) if hambatan else float("inf")
    else:
        hambatan = [l for l in lows if l < close]
        ruang = (close - max(hambatan)) if hambatan else float("inf")
    if ruang >= jarak_tp1:
        skor += 1
        alasan.append("jalan ke TP1 bersih")

    maks += 1
    r = dasar["rsi5m"]
    if (45 <= r <= 65) if buy else (35 <= r <= 55):
        skor += 1
        alasan.append("RSI sehat")

    if skor < min(skor_min, maks):
        return None
    dasar.update({"skor": skor, "skor_maks": maks, "alasan": alasan})
    return dasar


# ======================================================================
# Filter terpisah (dipakai buat eksperimen backtest & bisa dirakit ulang)
# ======================================================================
def _ctx(c5, c15, c1h, c4h, dasar):
    buy = dasar["arah"] == "BUY"
    c5x = c5[:-1]
    return buy, c5x, c15[:-1], c1h[:-1], (c4h[:-1] if c4h else None), c5x[-1], dasar["atr5m"], c5x[-1]["c"]


def f_candle(c5, c15, c1h, c4h, d):
    buy, c5x, *_, last, a, close = _ctx(c5, c15, c1h, c4h, d)
    rng = last["h"] - last["l"]
    if rng <= 0:
        return False
    pos = (last["c"] - last["l"]) / rng if buy else (last["h"] - last["c"]) / rng
    return abs(last["c"] - last["o"]) >= 0.4 * rng and pos >= 0.65


def f_tidak_jauh(c5, c15, c1h, c4h, d):
    buy, c5x, *_, last, a, close = _ctx(c5, c15, c1h, c4h, d)
    return abs(close - ema([c["c"] for c in c5x], 50)[-1]) <= 2.5 * a


def f_volatilitas(c5, c15, c1h, c4h, d):
    buy, c5x, *_, last, a, close = _ctx(c5, c15, c1h, c4h, d)
    trs = [max(c5x[i]["h"] - c5x[i]["l"], abs(c5x[i]["h"] - c5x[i - 1]["c"]), abs(c5x[i]["l"] - c5x[i - 1]["c"]))
           for i in range(max(1, len(c5x) - 200), len(c5x))]
    med = median(trs)
    return med <= 0 or 0.6 <= a / med <= 2.5


def f_adx(c5, c15, c1h, c4h, d):
    ad = adx(c15[:-1][-120:])
    return ad is not None and ad >= 20


def f_4h(c5, c15, c1h, c4h, d):
    if not c4h:
        return True
    return _bias(c4h[:-1]) == ("naik" if d["arah"] == "BUY" else "turun")


def f_volume(c5, c15, c1h, c4h, d):
    buy, c5x, *_, last, a, close = _ctx(c5, c15, c1h, c4h, d)
    vols = [c["v"] for c in c5x[-21:-1]]
    return sum(vols) <= 0 or last["v"] >= 1.2 * sum(vols) / len(vols)


def f_vwap(c5, c15, c1h, c4h, d):
    buy, c5x, *_, last, a, close = _ctx(c5, c15, c1h, c4h, d)
    vw = vwap_harian(c5x)
    return vw is None or ((close > vw) if buy else (close < vw))


def f_ruang(c5, c15, c1h, c4h, d):
    buy, c5x, c15x, c1hx, c4hx, last, a, close = _ctx(c5, c15, c1h, c4h, d)
    highs, lows = pivots(c1hx[-120:])
    jarak = abs(d["tp1"] - d["entry"])
    if buy:
        h = [x for x in highs if x > close]
        return not h or min(h) - close >= jarak
    l = [x for x in lows if x < close]
    return not l or close - max(l) >= jarak


def f_rsi(c5, c15, c1h, c4h, d):
    r = d["rsi5m"]
    return (45 <= r <= 65) if d["arah"] == "BUY" else (35 <= r <= 55)


def f_risk_min(c5, c15, c1h, c4h, d, pct=0.3):
    """SL minimal sekian % dari harga, biar fee nggak makan profit."""
    return d["risk_poin"] / d["entry"] * 100 >= pct


FILTER = {
    "candle": f_candle, "tidak_jauh": f_tidak_jauh, "volatilitas": f_volatilitas, "adx": f_adx,
    "4h": f_4h, "volume": f_volume, "vwap": f_vwap, "ruang": f_ruang, "rsi": f_rsi, "risk_min": f_risk_min,
}


def cari_setup_dengan(filters: list):
    """Bikin fungsi strategi: setup versi lama + daftar filter wajib."""
    def fn(c5, c15, c1h, c4h, digits):
        d = cari_setup(c5, c15, c1h, digits)
        if not d:
            return None
        for f in filters:
            if not FILTER[f](c5, c15, c1h, c4h, d):
                return None
        return d
    return fn
