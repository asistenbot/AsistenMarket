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
