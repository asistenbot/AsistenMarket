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
from scalper import cari_setup, cari_setup_v2
import backtest
import asyncio
import tracker
import sniper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# Jangan cetak URL lengkap (berisi token) ke log
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("asisten-market")

TZ = pytz.timezone(config.TIMEZONE)
_scalp_terakhir: dict = {}  # symbol -> (waktu, arah, entry)


# ---------- helper ----------
def is_owner(update: Update) -> bool:
    """Yang boleh pakai: user owner, baik di chat pribadi maupun di grup."""
    uid = update.effective_user.id if update.effective_user else None
    ok = uid in config.OWNER_CHAT_IDS
    m = update.effective_message
    logger.info("Perintah %r dari user %s di chat %s (topik %s) -> %s",
                m.text if m else None, uid, update.effective_chat.id if update.effective_chat else None,
                m.message_thread_id if m else None, "diproses" if ok else "DITOLAK (bukan owner)")
    return ok


def thread_of(update: Update):
    m = update.effective_message
    return m.message_thread_id if m and m.is_topic_message else None


async def kirim(bot, chat_id: int, teks: str, thread_id=None):
    """Kirim teks panjang dipecah per 4000 karakter (batas Telegram)."""
    while teks:
        potong = teks[:4000]
        if len(teks) > 4000:
            pos = potong.rfind("\n")
            if pos > 1000:
                potong = potong[:pos]
        await bot.send_message(chat_id=chat_id, text=potong, message_thread_id=thread_id)
        teks = teks[len(potong):].lstrip("\n")


TOPIK = {"pagi": "TOPIC_PAGI", "intraday": "TOPIC_INTRADAY", "scalp": "TOPIC_SCALP", "sniper": "TOPIC_SNIPER"}


async def kirim_ke_owner(bot, teks: str, jenis: str = "pagi"):
    """Kirim laporan otomatis: ke topik grup kalau grup sudah diatur, kalau belum ke chat pribadi owner."""
    if config.GROUP_CHAT_ID:
        try:
            await kirim(bot, config.GROUP_CHAT_ID, teks, getattr(config, TOPIK[jenis]) or None)
            return
        except Exception as e:
            logger.error("Gagal kirim ke grup (%s), pindah ke chat pribadi: %s", jenis, e)
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
    for sym in symbols or config.PAGI_SYMBOLS:
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
            c4h = await get_candles(sym, "4h", 150) if config.SCALP_VERSI == "v2" else None
        except Exception as e:
            logger.warning("Scan %s gagal: %s", sym, e)
            continue
        if config.SCALP_VERSI == "v2":
            s = cari_setup_v2(c5, c15, c1h, c4h, config.SYMBOLS[sym]["digits"], config.SCALP_SKOR_MIN)
        else:
            s = cari_setup(c5, c15, c1h, config.SYMBOLS[sym]["digits"])
        if not s:
            continue
        last = _scalp_terakhir.get(sym)
        if not paksa and last:
            waktu, arah, entry = last
            if arah == s["arah"] and time.time() - waktu < 2 * 3600 and abs(entry - s["entry"]) < 2 * s["atr5m"]:
                continue  # setup mirip baru saja dikirim
        _scalp_terakhir[sym] = (time.time(), s["arah"], s["entry"])
        baru = tracker.catat(sym, s, "manual" if paksa else "otomatis")
        teks = manager.format_scalp(sym, s)
        if not baru:
            teks += "\n(Sinyal searah untuk koin ini masih jalan, yang ini nggak dicatat ulang di rekap.)"
        pesan.append(teks)
    return pesan


# ---------- jadwal ----------
async def job_laporan_pagi(context: ContextTypes.DEFAULT_TYPE):
    try:
        for p in await buat_laporan_pagi():
            await kirim_ke_owner(context.bot, p, "pagi")
    except Exception as e:
        logger.exception("Laporan pagi gagal: %s", e)


async def job_intraday(context: ContextTypes.DEFAULT_TYPE):
    try:
        teks = await buat_update_intraday()
        if teks:
            await kirim_ke_owner(context.bot, teks, "intraday")
    except Exception as e:
        logger.exception("Update intraday gagal: %s", e)


async def job_scalping(context: ContextTypes.DEFAULT_TYPE):
    jam = datetime.now(TZ).hour
    if not (config.SCALP_JAM_MULAI <= jam < config.SCALP_JAM_SELESAI):
        return
    try:
        for p in await scan_scalping():
            await kirim_ke_owner(context.bot, p, "scalp")
    except Exception as e:
        logger.exception("Scan scalping gagal: %s", e)


async def scan_sniper(symbols=None, hanya_baru=True) -> tuple:
    """Cari rencana sniper. Return (pesan rencana, daftar koin yang belum ada setup)."""
    pesan, kosong = [], []
    for sym in symbols or config.SYMBOLS:
        if not pasar_buka(sym):
            kosong.append(f"{config.SYMBOLS[sym]['label']} (pasar tutup)")
            continue
        try:
            c1h = await get_candles(sym, "1h", 300)
            c4h = await get_candles(sym, "4h", 300)
            c1d = await get_candles(sym, "1d", 300)
        except Exception as e:
            logger.warning("Sniper %s gagal ambil data: %s", sym, e)
            kosong.append(f"{config.SYMBOLS[sym]['label']} (data gagal)")
            continue
        r = sniper.cari_rencana(sym, c1h, c4h, c1d)
        if not r:
            kosong.append(config.SYMBOLS[sym]["label"])
            continue
        baru = sniper.simpan(r)
        if baru or not hanya_baru:
            teks = sniper.format_rencana(r)
            if not baru:
                teks += "\n(Rencana ini udah pernah dikirim / koin ini lagi ada posisi sniper aktif.)"
            pesan.append(teks)
    return pesan, kosong


async def job_sniper_scan(context: ContextTypes.DEFAULT_TYPE):
    try:
        pesan, _ = await scan_sniper()
        for p in pesan:
            await kirim_ke_owner(context.bot, p, "sniper")
    except Exception as e:
        logger.exception("Scan sniper gagal: %s", e)


async def job_sniper_pantau(context: ContextTypes.DEFAULT_TYPE):
    try:
        for p in await sniper.pantau(get_candles, pasar_buka):
            await kirim_ke_owner(context.bot, p, "sniper")
    except Exception as e:
        logger.exception("Pantau sniper gagal: %s", e)


async def job_cek_sinyal(context: ContextTypes.DEFAULT_TYPE):
    """Cek sinyal scalping yang masih jalan: sudah kena TP atau SL?"""
    try:
        for p in await tracker.cek_semua(get_candles):
            await kirim_ke_owner(context.bot, p, "scalp")
    except Exception as e:
        logger.exception("Cek sinyal gagal: %s", e)


async def job_rekap_mingguan(context: ContextTypes.DEFAULT_TYPE):
    await kirim_ke_owner(context.bot, tracker.rekap(7) + "\n\n" + sniper.rekap(7), "scalp")


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
    cid = update.effective_user.id
    if not is_owner(update):
        await update.message.reply_text(
            f"Halo! Chat ID kamu: {cid}\nBot ini privat. Kasih ID ini ke admin biar bisa dipakai."
        )
        return
    await update.message.reply_text(
        "Asisten Market siap 📊\n\n"
        "/laporan — laporan XAU, BTC, ETH (sama kayak laporan pagi)\n"
        "/laporan semua — laporan semua pair\n"
        "/laporan xau — laporan satu pair (bisa: btc, eth, sol, sui, tao, hype, ondo, aster)\n"
        "/intraday — update 4H, 1H, 15m\n"
        "/scalp — cek ide scalping sekarang\n"
        "/harga — harga terakhir\n"
        "/sniper — rencana limit order sniper (bisa /sniper xau)\n"
        "/sniper aktif — rencana sniper yang lagi jalan\n"
        "/rekap — hasil scalping & sniper 7 hari (bisa /rekap 30)\n"
        "/uji — tes strategi scalping ke data 30 hari terakhir (bisa /uji 14)\n\n"
        "Jadwal otomatis (WIB):\n"
        f"07:00 laporan pagi ({', '.join(config.SYMBOLS[s]['label'] for s in config.PAGI_SYMBOLS)})\n"
        + ("11:00, 15:00, 19:00, 23:00 update intraday\n" if config.AUTO_INTRADAY else "Intraday: kirim /intraday kalau butuh\n")
        + ("14:00–24:00 ide scalping kalau ada setup\n\n" if config.AUTO_SCALP else "Scalping: kirim /scalp kalau butuh\n\n") +
        f"Pair: {', '.join(v['label'] for v in config.SYMBOLS.values())}"
    )


async def _proses(update: Update, context, fungsi, *a):
    if not is_owner(update):
        return
    await update.message.reply_text("Sebentar, lagi dianalisa... ⏳")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING,
                                       message_thread_id=thread_of(update))
    try:
        hasil = await fungsi(*a)
    except Exception as e:
        logger.exception("Perintah gagal: %s", e)
        await update.message.reply_text(f"Gagal: {e}")
        return
    return hasil


async def cmd_laporan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Tanpa nama koin: sama dengan laporan pagi (XAU, BTC, ETH). Pakai /laporan semua untuk semua pair.
    if not context.args:
        symbols = config.PAGI_SYMBOLS
    elif context.args[0].lower() == "semua":
        symbols = list(config.SYMBOLS)
    else:
        symbols = pilih_symbol(context.args)
    hasil = await _proses(update, context, buat_laporan_pagi, symbols)
    for p in hasil or []:
        await kirim(context.bot, update.effective_chat.id, p, thread_of(update))


async def cmd_intraday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    teks = await _proses(update, context, buat_update_intraday, pilih_symbol(context.args))
    await kirim(context.bot, update.effective_chat.id, teks or "Pasar lagi tutup.", thread_of(update))


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
        await kirim(context.bot, update.effective_chat.id, p, thread_of(update))


async def cmd_rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    hari = 7
    if context.args and context.args[0].isdigit():
        hari = max(1, min(365, int(context.args[0])))
    await kirim(context.bot, update.effective_chat.id, tracker.rekap(hari) + "\n\n" + sniper.rekap(hari),
                thread_of(update))


async def cmd_sniper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if context.args and context.args[0].lower() in ("aktif", "list", "jalan"):
        await kirim(context.bot, update.effective_chat.id, sniper.format_daftar(), thread_of(update))
        return
    hasil = await _proses(update, context, scan_sniper, pilih_symbol(context.args), False)
    if hasil is None:
        return
    pesan, kosong = hasil
    for p in pesan:
        await kirim(context.bot, update.effective_chat.id, p, thread_of(update))
    if kosong:
        await kirim(context.bot, update.effective_chat.id,
                    "Belum ada setup sniper (RR minimal 1:3, searah trend 4H/1D) untuk:\n• " + "\n• ".join(kosong),
                    thread_of(update))


_uji_jalan = False


async def _uji_background(bot, chat_id, thread_id, hari):
    global _uji_jalan
    try:
        teks, _ = await backtest.uji_semua(hari)
        await kirim(bot, chat_id, teks, thread_id)
    except Exception as e:
        logger.exception("Backtest gagal: %s", e)
        await kirim(bot, chat_id, f"Backtest gagal: {e}", thread_id)
    finally:
        _uji_jalan = False


async def cmd_uji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _uji_jalan
    if not is_owner(update):
        return
    if _uji_jalan:
        await update.effective_message.reply_text("Backtest masih jalan, tunggu hasilnya dulu ya.")
        return
    hari = 30
    if context.args and context.args[0].isdigit():
        hari = max(3, min(60, int(context.args[0])))
    _uji_jalan = True
    await update.effective_message.reply_text(
        f"🧪 Lagi ngetes strategi scalping ke data {hari} hari terakhir untuk semua koin. "
        "Butuh beberapa menit, hasilnya nanti dikirim ke sini.")
    asyncio.create_task(_uji_background(context.bot, update.effective_chat.id, thread_of(update), hari))


async def job_backtest_awal(context: ContextTypes.DEFAULT_TYPE):
    try:
        teks, _ = await backtest.uji_semua(30, strategi=backtest.strategi_eksperimen())
        for baris in teks.split("\n"):
            logger.info("HASIL BACKTEST | %s", baris)
    except Exception as e:
        logger.exception("Backtest awal gagal: %s", e)


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


async def cmd_idtopik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kirim di dalam topik grup untuk tahu ID grup & topiknya."""
    if not is_owner(update):
        return
    await update.effective_message.reply_text(
        f"Grup ID: {update.effective_chat.id}\nTopik ID: {thread_of(update) or '-'}"
    )


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error saat proses update: %s", context.error, exc_info=context.error)


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN belum diisi")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("laporan", cmd_laporan))
    app.add_handler(CommandHandler("intraday", cmd_intraday))
    app.add_handler(CommandHandler("scalp", cmd_scalp))
    app.add_handler(CommandHandler("harga", cmd_harga))
    app.add_handler(CommandHandler("idtopik", cmd_idtopik))
    app.add_handler(CommandHandler("rekap", cmd_rekap))
    app.add_handler(CommandHandler("sniper", cmd_sniper))
    app.add_handler(CommandHandler("uji", cmd_uji))
    app.add_error_handler(on_error)

    jq = app.job_queue
    h, m = config.JAM_LAPORAN_PAGI
    jq.run_daily(job_laporan_pagi, dtime(h, m, tzinfo=TZ), name="laporan_pagi")
    if config.AUTO_INTRADAY:
        for h, m in config.JAM_UPDATE_INTRADAY:
            jq.run_daily(job_intraday, dtime(h, m, tzinfo=TZ), name=f"intraday_{h}")
    jq.run_once(job_cek_awal, when=5, name="cek_awal")
    if config.BACKTEST_SAAT_START:
        jq.run_once(job_backtest_awal, when=30, name="backtest_awal")
    if config.AUTO_SCALP:
        jq.run_repeating(job_scalping, interval=config.SCALP_TIAP_MENIT * 60, first=60, name="scalping")

    jq.run_repeating(job_cek_sinyal, interval=10 * 60, first=120, name="cek_sinyal")
    jq.run_repeating(job_sniper_pantau, interval=5 * 60, first=90, name="sniper_pantau")
    if config.AUTO_SNIPER:
        jq.run_repeating(job_sniper_scan, interval=60 * 60, first=180, name="sniper_scan")
    jq.run_daily(job_rekap_mingguan, dtime(21, 0, tzinfo=TZ), days=(0,), name="rekap_mingguan")  # Minggu
    if not tracker.penyimpanan_permanen():
        logger.warning("DATA_DIR %s bukan volume: catatan sinyal bakal hilang kalau bot restart.", tracker.DATA_DIR)

    if not config.OWNER_CHAT_IDS:
        logger.warning("OWNER_CHAT_IDS kosong: kirim /start ke bot untuk lihat chat ID.")
    logger.info("Asisten Market jalan. Pair: %s | scalper %s (skor min %s)", ", ".join(config.SYMBOLS),
                config.SCALP_VERSI, config.SCALP_SKOR_MIN)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
