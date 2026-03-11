"""Telegram Bot Sender V4
Kupon ve yorum mesajları AYRI AYRI gönderilir.
Mesaj bölme, retry, rate limit koruması.
"""
import asyncio
import logging
from telegram import Bot
from telegram.error import RetryAfter, TimedOut
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

MAX_MSG_LENGTH = 4096  # Telegram max
INTER_MESSAGE_DELAY = 1.5  # saniye — rate limit koruması
MAX_RETRIES = 3


# ═══════════════════════════════════════════════════════════
# CORE SEND
# ═══════════════════════════════════════════════════════════

async def _send_single(bot, text, parse_mode=None):
    """Tek mesaj gönder, retry ile"""
    for attempt in range(MAX_RETRIES):
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
                parse_mode=parse_mode,
            )
            return True
        except RetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"Rate limited, {wait}s bekleniyor...")
            await asyncio.sleep(wait)
        except TimedOut:
            logger.warning(f"Timeout, attempt {attempt+1}/{MAX_RETRIES}")
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
    return False


async def send_message(text, parse_mode=None):
    """Tek mesaj gönder (uzunsa böl)"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set, printing to console")
        print(text)
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    chunks = _split_message(text)

    for chunk in chunks:
        success = await _send_single(bot, chunk, parse_mode)
        if not success:
            logger.error("Mesaj gönderilemedi, console'a yazdırılıyor")
            print(chunk)
        if len(chunks) > 1:
            await asyncio.sleep(INTER_MESSAGE_DELAY)


# ═══════════════════════════════════════════════════════════
# AYRI AYRI GÖNDER — KUPON + YORUM
# ═══════════════════════════════════════════════════════════

async def send_altili_package(kupon_text, commentary_text, parse_mode=None):
    """
    Bir altılı için kupon + yorum mesajlarını ayrı ayrı gönder.

    Sıralama:
    1. Kupon mesajı (kısa, net — hemen bakılacak)
    2. 2 saniye bekle
    3. Yorum mesajı (detaylı analiz)
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set, printing to console")
        print("=" * 40)
        print(kupon_text)
        print("=" * 40)
        print(commentary_text)
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # 1. Kupon mesajı
    logger.info("Kupon mesajı gönderiliyor...")
    kupon_chunks = _split_message(kupon_text)
    for chunk in kupon_chunks:
        await _send_single(bot, chunk, parse_mode)
        await asyncio.sleep(INTER_MESSAGE_DELAY)

    # 2. Ara — Telegram'da "ayrı mesaj" hissi versin
    await asyncio.sleep(2.0)

    # 3. Yorum mesajı
    logger.info("Yorum mesajı gönderiliyor...")
    commentary_chunks = _split_message(commentary_text)
    for chunk in commentary_chunks:
        await _send_single(bot, chunk, parse_mode)
        await asyncio.sleep(INTER_MESSAGE_DELAY)

    logger.info("Altılı paketi gönderildi ✓")


async def send_daily_package(daily_header, altili_packages, no_play_message=None):
    """
    Günlük tüm altılıları gönder.

    Args:
        daily_header: str — günlük başlık
        altili_packages: list of (kupon_text, commentary_text) tuples
        no_play_message: str or None — oynamaya değer altılı yoksa
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set")
        print(daily_header)
        if no_play_message:
            print(no_play_message)
        for kupon, commentary in altili_packages:
            print(kupon)
            print(commentary)
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # 1. Günlük header
    await _send_single(bot, daily_header, "HTML")
    await asyncio.sleep(INTER_MESSAGE_DELAY)

    if no_play_message:
        await _send_single(bot, no_play_message)
        return

    # 2. Her altılı için kupon + yorum
    for i, (kupon_text, commentary_text) in enumerate(altili_packages):
        if i > 0:
            # Altılılar arası separator
            await asyncio.sleep(2.0)
            await _send_single(bot, "━" * 25)
            await asyncio.sleep(INTER_MESSAGE_DELAY)

        await send_altili_package(kupon_text, commentary_text, "HTML")

    # 3. Kapanış
    await asyncio.sleep(INTER_MESSAGE_DELAY)
    await _send_single(bot, "🏇 İyi şanslar! Sorumlu oyna. 🍀")


# ═══════════════════════════════════════════════════════════
# SYNC WRAPPER'LAR
# ═══════════════════════════════════════════════════════════

def send_sync(text, parse_mode=None):
    """Synchronous wrapper for send_message"""
    asyncio.run(send_message(text, parse_mode))


def send_altili_sync(kupon_text, commentary_text, parse_mode=None):
    """Synchronous wrapper for send_altili_package"""
    asyncio.run(send_altili_package(kupon_text, commentary_text, parse_mode))


def send_daily_sync(daily_header, altili_packages, no_play_message=None):
    """Synchronous wrapper for send_daily_package"""
    asyncio.run(send_daily_package(daily_header, altili_packages, no_play_message))


# ═══════════════════════════════════════════════════════════
# MESAJ BÖLME
# ═══════════════════════════════════════════════════════════

def _split_message(text):
    """
    Mesajı Telegram limitine göre böl.
    Satır ortasından kesmez — her zaman newline'dan böler.
    """
    if len(text) <= MAX_MSG_LENGTH:
        return [text]

    chunks = []
    lines = text.split('\n')
    current = ""

    for line in lines:
        # Tek satır bile limiti aşıyorsa zorla böl
        if len(line) > MAX_MSG_LENGTH:
            if current:
                chunks.append(current)
                current = ""
            # Hard split
            for j in range(0, len(line), MAX_MSG_LENGTH):
                chunks.append(line[j:j + MAX_MSG_LENGTH])
            continue

        if len(current) + len(line) + 1 > MAX_MSG_LENGTH:
            chunks.append(current)
            current = line
        else:
            current += ("\n" + line) if current else line

    if current:
        chunks.append(current)

    return chunks


# ═══════════════════════════════════════════════════════════
# HEADER / FORMAT HELPERS
# ═══════════════════════════════════════════════════════════

def format_daily_header(date_str, n_hippodromes, n_altilis):
    """Günlük özet header"""
    return (
        f"<b>TJK 6'LI GANYAN — {date_str}</b>\n"
        f"{n_hippodromes} hipodrom, {n_altilis} altili dizi"
    )


def format_no_play_message(date_str):
    """Oynamaya değer altılı yoksa"""
    return (
        f"🏇 TJK — {date_str}\n"
        f"📊 Bugün oynamaya değer altılı yok.\n"
        f"Model emin değil, para biriktir. 💰"
    )
