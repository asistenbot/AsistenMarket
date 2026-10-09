"""Manajer: rangkum hasil analis jadi laporan Telegram (pakai AI, ada cadangan tanpa AI)."""
import json
import logging
from datetime import datetime

import pytz

import config
from analysts import NAMA_TF

logger = logging.getLogger(__name__)

_client = None
if config.ANTHROPIC_API_KEY:
    from anthropic import AsyncAnthropic

    _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM = (
    "Kamu adalah manajer analis market yang menulis laporan untuk bos via Telegram. "
    "Bahasa Indonesia santai tapi jelas (pakai 'lu/gua' boleh). "
    "WAJIB: hanya pakai angka yang ada di data JSON, jangan mengarang harga atau level baru. "
    "Kalau ada timeframe yang error/kosong, bilang datanya belum ada. "
    "Format teks polos untuk Telegram: tanpa markdown, tanpa tanda bintang, tanpa tabel, tanpa #. "
    "Boleh pakai emoji secukupnya (📈 📉 ⚠️ 🎯) dan baris kosong antar bagian. "
    "Ini analisa teknikal, bukan saran keuangan; keputusan tetap di tangan bos. Singkat, padat, langsung ke poin."
)


def sekarang() -> str:
    return datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%d %b %Y %H:%M WIB")


async def _tulis(prompt: str, model: str, max_tokens: int = 1500) -> str | None:
    if not _client:
        return None
    try:
        msg = await _client.messages.create(
            model=model, max_tokens=max_tokens, system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception as e:
        logger.error("AI gagal nulis laporan: %s", e)
        return None


def _baris_tf(tf: str, s: dict) -> str:
    if "error" in s:
        return f"{NAMA_TF.get(tf, tf)}: data belum ada"
    return (f"{NAMA_TF.get(tf, tf)}: trend {s['trend']}, RSI {s['rsi14']}, "
            f"S {', '.join(map(str, s['support']))} | R {', '.join(map(str, s['resistance']))}")


def _cadangan(judul: str, data: dict) -> str:
    """Laporan polos tanpa AI (dipakai kalau AI tidak tersedia)."""
    out = [f"{judul}\n{sekarang()}"]
    for sym, tfs in data.items():
        out.append(f"\n{config.SYMBOLS[sym]['label']}")
        harga = next((s["harga"] for s in reversed(list(tfs.values())) if "harga" in s), None)
        if harga is not None:
            out.append(f"Harga: {harga}")
        for tf, s in tfs.items():
            out.append("• " + _baris_tf(tf, s))
    return "\n".join(out)


async def laporan_pagi(data: dict) -> str:
    """data = {symbol: {tf: ringkasan}} berisi semua timeframe 3M..15m."""
    prompt = (
        f"Waktu: {sekarang()}. Bikin LAPORAN PAGI untuk tiap pair di bawah. Untuk tiap pair tulis:\n"
        "1. Gambaran besar (3 bulan, bulanan, mingguan, harian): arah trend utama.\n"
        "2. Intraday (4 jam, 1 jam, 15 menit): kondisi sekarang.\n"
        "3. Level penting hari ini: support & resistance terdekat.\n"
        "4. Skenario: kalau naik tembus level X → target Y; kalau turun tembus level A → target B.\n"
        "5. Satu kalimat kesimpulan bias hari ini (buy/sell/tunggu).\n"
        "Tutup dengan satu baris pengingat soal risiko.\n\n"
        f"DATA:\n{json.dumps(data, ensure_ascii=False)}"
    )
    teks = await _tulis(prompt, config.CLAUDE_MODEL, 2500)
    return teks or _cadangan("☀️ LAPORAN PAGI", data)


async def update_intraday(data: dict) -> str:
    prompt = (
        f"Waktu: {sekarang()}. Bikin UPDATE INTRADAY singkat (maks 5 baris per pair): "
        "arah 4 jam/1 jam/15 menit, level terdekat yang perlu diawasi, dan bias jangka pendek.\n\n"
        f"DATA:\n{json.dumps(data, ensure_ascii=False)}"
    )
    teks = await _tulis(prompt, config.CLAUDE_MODEL_FAST, 1200)
    return teks or _cadangan("⏱ UPDATE INTRADAY", data)


def format_scalp(symbol: str, s: dict) -> str:
    label = config.SYMBOLS[symbol]["label"]
    ikon = "🟢" if s["arah"] == "BUY" else "🔴"
    return (
        f"{ikon} IDE SCALPING {label}\n{sekarang()}\n\n"
        f"Arah: {s['arah']} ({s['jenis']})\n"
        f"Entry: {s['entry']}\n"
        f"Stop loss: {s['sl']}\n"
        f"TP1: {s['tp1']} (1.5R)\n"
        f"TP2: {s['tp2']} (2.5R)\n\n"
        f"Trend 15m: {s['trend_15m']}, 1h: {s['trend_1h']} | RSI 5m: {s['rsi5m']}\n"
        "⚠️ Cek chart dulu sebelum entry. Pakai lot kecil, SL wajib dipasang."
    )
