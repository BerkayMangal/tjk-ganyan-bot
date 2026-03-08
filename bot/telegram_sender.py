"""Telegram Bot Sender
Formats and sends ganyan predictions via Telegram
"""
import asyncio
import logging
from telegram import Bot
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

MAX_MSG_LENGTH = 4096  # Telegram max message length


async def send_message(text, parse_mode=None):
    """Send a message via Telegram bot"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set, printing to console")
        print(text)
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Split long messages
    chunks = _split_message(text)

    for chunk in chunks:
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=chunk,
                parse_mode=parse_mode,
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            print(chunk)


def send_sync(text, parse_mode=None):
    """Synchronous wrapper for send_message"""
    asyncio.run(send_message(text, parse_mode))


def _split_message(text):
    """Split message into chunks under MAX_MSG_LENGTH"""
    if len(text) <= MAX_MSG_LENGTH:
        return [text]

    chunks = []
    lines = text.split('\n')
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > MAX_MSG_LENGTH:
            chunks.append(current)
            current = line
        else:
            current += ("\n" + line) if current else line

    if current:
        chunks.append(current)

    return chunks


def format_daily_header(date_str, n_hippodromes, n_altilis):
    """Format daily summary header"""
    return (
        f"🏇🏇🏇 TJK 6'LI GANYAN — {date_str} 🏇🏇🏇\n"
        f"{'='*40}\n"
        f"📍 {n_hippodromes} hipodrom, {n_altilis} altılı dizi\n"
        f"{'='*40}\n"
    )


def format_no_play_message(date_str):
    """Message when there are no races or no good plays"""
    return (
        f"🏇 TJK — {date_str}\n"
        f"📊 Bugün oynamaya değer altılı yok.\n"
        f"Model emin değil, para biriktir. 💰"
    )
