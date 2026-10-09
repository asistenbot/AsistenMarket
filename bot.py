"""Asisten Market — bot Telegram analisa XAU/USD & crypto.

Peran:
  Kurir data   → data.py
  Analis swing → analysts.py (3M, 1M, 1W, 1D)
  Analis intraday → analysts.py (4H, 1H, 15m)
  Scalper      → scalper.py (5m, searah 15m & 1H)
  Manajer      → manager.py (rangkum & kirim ke Telegram)
"""
import logging
import time
from datetime import datetime, time as dtime

import pytz
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import manager
from analysts import TF_INTRADAY, TF_SWING, analisa
from data import get_candles, pasar_buka
from scalper import cari_setup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# Jangan cetak URL lengkap (berisi token) ke log
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("asisten-market")

TZ = pytz.timezone(config.TIMEZONE)
_scalp_terakhir: dict = {}  # symbol -> (waktu, arah, entry)


# ---------- helper ----------
def is_owner(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.id in config.OWNER_CHAT_IDS


async def kirim(bot, chat_id: int, teks: str):
    """Kirim teks panjang dipecah per 4000 karakter (batas Telegram)."""
    while teks:
        potong = teks[:4000]
        if len(teks) > 4000:
            pos = potong.rfind("\n")
            if pos > 1000:
                potong = potong[:pos]
        await bot.send_message(chat_id=chat_id, text=potong)
        teks = teks[len(potong):].lstrip("\n")


async def kirim_ke_owner(bot, teks: str):
    for cid in config.OWNER_CHAT_IDS:
        try:
            await kirim(bot, cid, teks)
        except Exception as e:
            logger.error("Gagal kirim ke %s: %s", cid, e)


def pilih_symbol(args) -> list:
    if not args:
        return list(config.SYMBOLS)
    q = args[0].upper().replace("/", "")
    cocok = [s for s in config.SYMBOLS if q in s or s.startswith(q)]
    return cocok or list(config.SYMBOLS)


# ---------- pekerjaan inti ----------
async def buat_laporan_pagi(symbols=None) -> list:
    """Satu pesan per pair, biar rapi dan nggak kepanjangan."""
    pesan = [f"☀️ LAPORAN PAGI — {manager.sekarang()}\n"
             "Gambaran besar (3M, 1M, 1W, 1D) + intraday (4H, 1H, 15m) per pair.\n"
             "⚠️ Analisa teknikal otomatis, bukan saran keuangan."]
    for sym in symbols or config.SYMBOLS:
        data = {sym: await analisa(sym, TF_SWING + TF_INTRADAY)}
        if all("error" in v for v in data[sym].values()):
            pesan.append(f"{config.SYMBOLS[sym]['label']}: data belum bisa diambil.")
            continue
        pesan.append(await manager.laporan_pagi(data))
    return pesan


async def buat_update_intraday(symbols=None) -> str | None:
    data = {}
    for sym in symbols or config.SYMBOLS:
        if pasar_buka(sym):
            data[sym] = await analisa(sym, TF_INTRADAY)
    if not data:
        return None
    return await manager.update_intraday(data)


async def scan_scalping(symbols=None, paksa=False) -> list:
    """Return list pesan ide scalping. paksa=True: abaikan filter anti-spam."""
    pesan = []
    for sym in symbols or config.SYMBOLS:
        if not pasar_buka(sym):
            continue
        try:
            c5 = await get_candles(sym, "5m", 300)
            c15 = await get_candles(sym, "15m", 300)
            c1h = await get_candles(sym, "1h", 300)
        except Exception as e:
            logger.warning("Scan %s gagal: %s", sym, e)
            continue
        s = cari_setup(c5, c15, c1h, config.SYMBOLS[sym]["digits"])
        if not s:
            continue
        last = _scalp_terakhir.get(sym)
        if not paksa and last:
            waktu, arah, entry = last
            if arah == s["arah"] and time.time() - waktu < 2 * 3600 and abs(entry - s["entry"]) < 2 * s["atr5m"]:
                continue  # setup mirip baru saja dikirim
        _scalp_terakhir[sym] = (time.time(), s["arah"], s["entry"])
        pesan.append(manager.format_scalp(sym, s))
    return pesan


# ---------- jadwal ----------
async def job_laporan_pagi(context: ContextTypes.DEFAULT_TYPE):
    try:
        for p in await buat_laporan_pagi():
            await kirim_ke_owner(context.bot, p)
    except Exception as e:
        logger.exception("Laporan pagi gagal: %s", e)


async def job_intraday(context: ContextTypes.DEFAULT_TYPE):
    try:
        teks = await buat_update_intraday()
        if teks:
            await kirim_ke_owner(context.bot, teks)
    except Exception as e:
        logger.exception("Update intraday gagal: %s", e)


async def job_scalping(context: ContextTypes.DEFAULT_TYPE):
    jam = datetime.now(TZ).hour
    if not (config.SCALP_JAM_MULAI <= jam < config.SCALP_JAM_SELESAI):
        return
    try:
        for p in await scan_scalping():
            await kirim_ke_owner(context.bot, p)
    except Exception as e:
        logger.exception("Scan scalping gagal: %s", e)


async def job_cek_awal(context: ContextTypes.DEFAULT_TYPE):
    """Cek semua sumber data sekali waktu bot nyala, hasilnya dicatat di log."""
    for sym, info in config.SYMBOLS.items():
        try:
            c = await get_candles(sym, "15m", 100)
            logger.info("CEK DATA %s OK: harga %s (%d candle)", sym, round(c[-1]["c"], info["digits"]), len(c))
        except Exception as e:
            logger.error("CEK DATA %s GAGAL: %s", sym, e)


# ---------- perintah ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if not is_owner(update):
        await update.message.reply_text(
            f"Halo! Chat ID kamu: {cid}\nBot ini privat. Kasih ID ini ke admin biar bisa dipakai."
        )
        return
    await update.message.reply_text(
        "Asisten Market siap 📊\n\n"
        "/laporan — laporan lengkap semua timeframe\n"
        "/laporan xau — laporan satu pair (bisa: btc, eth, sol, sui, tao, hype, ondo, aster)\n"
        "/intraday — update 4H, 1H, 15m\n"
        "/scalp — cek ide scalping sekarang\n"
        "/harga — harga terakhir\n\n"
        "Jadwal otomatis (WIB):\n"
        "07:00 laporan pagi\n"
        "11:00, 15:00, 19:00, 23:00 update intraday\n"
        "14:00–24:00 ide scalping kalau ada setup\n\n"
        f"Pair: {', '.join(v['label'] for v in config.SYMBOLS.values())}"
    )


async def _proses(update: Update, context, fungsi, *a):
    if not is_owner(update):
        return
    await update.message.reply_text("Sebentar, lagi dianalisa... ⏳")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        hasil = await fungsi(*a)
    except Exception as e:
        logger.exception("Perintah gagal: %s", e)
        await update.message.reply_text(f"Gagal: {e}")
        return
    return hasil


async def cmd_laporan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hasil = await _proses(update, context, buat_laporan_pagi, pilih_symbol(context.args))
    for p in hasil or []:
        await kirim(context.bot, update.effective_chat.id, p)


async def cmd_intraday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    teks = await _proses(update, context, buat_update_intraday, pilih_symbol(context.args))
    await kirim(context.bot, update.effective_chat.id, teks or "Pasar lagi tutup.")


async def cmd_scalp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    hasil = await _proses(update, context, scan_scalping, pilih_symbol(context.args), True)
    if hasil is None:
        return
    if not hasil:
        await update.message.reply_text(
            "Belum ada setup scalping yang bagus sekarang. Trend 15m & 1h belum searah atau harga belum di area entry. "
            "Mending tunggu 👀"
        )
    for p in hasil:
        await kirim(context.bot, update.effective_chat.id, p)


async def cmd_harga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    baris = [f"💰 Harga terakhir — {manager.sekarang()}"]
    for sym, info in config.SYMBOLS.items():
        try:
            c = await get_candles(sym, "15m", 100)
            baris.append(f"{info['label']}: {round(c[-1]['c'], info['digits'])}"
                         + ("" if pasar_buka(sym) else " (pasar tutup)"))
        except Exception as e:
            baris.append(f"{info['label']}: gagal ({e})")
    await update.message.reply_text("\n".join(baris))


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN belum diisi")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("laporan", cmd_laporan))
    app.add_handler(CommandHandler("intraday", cmd_intraday))
    app.add_handler(CommandHandler("scalp", cmd_scalp))
    app.add_handler(CommandHandler("harga", cmd_harga))

    jq = app.job_queue
    h, m = config.JAM_LAPORAN_PAGI
    jq.run_daily(job_laporan_pagi, dtime(h, m, tzinfo=TZ), name="laporan_pagi")
    for h, m in config.JAM_UPDATE_INTRADAY:
        jq.run_daily(job_intraday, dtime(h, m, tzinfo=TZ), name=f"intraday_{h}")
    jq.run_once(job_cek_awal, when=5, name="cek_awal")
    jq.run_repeating(job_scalping, interval=config.SCALP_TIAP_MENIT * 60, first=60, name="scalping")

    if not config.OWNER_CHAT_IDS:
        logger.warning("OWNER_CHAT_IDS kosong: kirim /start ke bot untuk lihat chat ID.")
    logger.info("Asisten Market jalan. Pair: %s", ", ".join(config.SYMBOLS))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
