"""Hitungan teknikal murni (tanpa AI): EMA, RSI, ATR, support/resistance, arah trend."""


def ema(values: list, period: int) -> list:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


def atr(candles: list, period: int = 14) -> float | None:
    if len(candles) < 2:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return sum(trs) / len(trs)
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def pivots(candles: list, w: int = 3):
    """Cari titik swing high & swing low."""
    highs, lows = [], []
    for i in range(w, len(candles) - w):
        h = candles[i]["h"]
        l = candles[i]["l"]
        if all(h >= candles[j]["h"] for j in range(i - w, i + w + 1)):
            highs.append(h)
        if all(l <= candles[j]["l"] for j in range(i - w, i + w + 1)):
            lows.append(l)
    return highs, lows


def _merge_levels(levels: list, tol: float) -> list:
    levels = sorted(levels)
    merged = []
    for lv in levels:
        if merged and abs(lv - merged[-1][0]) <= tol:
            n = merged[-1][1] + 1
            merged[-1] = ((merged[-1][0] * merged[-1][1] + lv) / n, n)
        else:
            merged.append((lv, 1))
    return [m[0] for m in merged]


def support_resistance(candles: list, a: float | None, jumlah: int = 2):
    close = candles[-1]["c"]
    highs, lows = pivots(candles)
    tol = (a or close * 0.002) * 0.5
    levels = _merge_levels(highs + lows, tol)
    resist = sorted([x for x in levels if x > close])[:jumlah]
    support = sorted([x for x in levels if x < close], reverse=True)[:jumlah]
    # Kalau tidak ada swing, pakai high/low tertinggi-terendah
    if not resist:
        resist = [max(c["h"] for c in candles)]
    if not support:
        support = [min(c["l"] for c in candles)]
    return support, resist


def trend_label(close, e20, e50, e200, slope20) -> str:
    if e20 is None or e50 is None:
        return "belum jelas"
    score = 0
    score += 1 if close > e20 else -1
    score += 1 if e20 > e50 else -1
    score += 1 if slope20 > 0 else -1
    if e200 is not None:
        score += 1 if close > e200 else -1
    if score >= 3:
        return "naik"
    if score <= -3:
        return "turun"
    return "sideways"


def summarize(candles: list, digits: int = 2) -> dict:
    """Ringkasan satu timeframe untuk dibaca analis/AI."""
    closes = [c["c"] for c in candles]
    close = closes[-1]
    e20 = ema(closes, 20) if len(closes) >= 20 else None
    e50 = ema(closes, 50) if len(closes) >= 50 else None
    e200 = ema(closes, 200) if len(closes) >= 200 else None
    a = atr(candles)
    slope = (e20[-1] - e20[-4]) if e20 and len(e20) >= 4 else 0
    sup, res = support_resistance(candles[-120:], a)
    prev = closes[-2] if len(closes) >= 2 else close
    r = lambda x: round(x, digits) if x is not None else None  # noqa: E731
    recent = candles[-20:]
    return {
        "harga": r(close),
        "perubahan_candle_terakhir_pct": round((close - prev) / prev * 100, 2) if prev else 0,
        "ema20": r(e20[-1]) if e20 else None,
        "ema50": r(e50[-1]) if e50 else None,
        "ema200": r(e200[-1]) if e200 else None,
        "rsi14": round(rsi(closes), 1) if rsi(closes) is not None else None,
        "atr14": r(a),
        "trend": trend_label(close, e20[-1] if e20 else None, e50[-1] if e50 else None,
                             e200[-1] if e200 else None, slope),
        "support": [r(x) for x in sup],
        "resistance": [r(x) for x in res],
        "high_20_candle": r(max(c["h"] for c in recent)),
        "low_20_candle": r(min(c["l"] for c in recent)),
        "jumlah_candle": len(candles),
    }
