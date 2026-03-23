"""
Send price-drop alerts via Telegram.

Setup (one-time):
  1. Message @BotFather on Telegram → /newbot → copy the token.
  2. Message your new bot once (so it has your chat_id).
  3. Visit https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat_id.
  4. Put both values in config.yaml under telegram.bot_token / telegram.chat_id.
"""
from __future__ import annotations
import httpx

from .models import PriceDrop, ProductSnapshot
from .comparator import build_price_matrix


def _telegram_send(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = httpx.post(url, json=payload, timeout=15)
    resp.raise_for_status()


def send_drop_alert(
    drops: list[PriceDrop],
    snapshot: ProductSnapshot,
    bot_token: str,
    chat_id: str,
) -> None:
    """Send a Telegram message listing all price drops + the full price matrix."""
    if not drops:
        return

    # Drop summary
    drop_lines = []
    for d in drops:
        drop_lines.append(
            f"  {d.attr_label}: {d.currency} {d.old_price:.2f} → "
            f"<b>{d.currency} {d.new_price:.2f}</b> (-{d.drop_pct}%)"
        )

    matrix = build_price_matrix(snapshot)

    msg = (
        f"🔔 <b>Price Drop Alert</b>\n"
        f"<b>{snapshot.product_name}</b>\n"
        f"{snapshot.url}\n\n"
        f"<b>Drops detected:</b>\n"
        + "\n".join(drop_lines)
        + f"\n\n<b>Full price matrix:</b>\n<pre>{matrix}</pre>"
    )

    _telegram_send(bot_token, chat_id, msg)


def send_daily_summary(
    snapshot: ProductSnapshot,
    bot_token: str,
    chat_id: str,
) -> None:
    """Send the current price matrix even if no drops (optional daily digest)."""
    matrix = build_price_matrix(snapshot)
    msg = (
        f"📋 <b>Daily Price Check</b>\n"
        f"<b>{snapshot.product_name}</b>\n"
        f"{snapshot.url}\n\n"
        f"<pre>{matrix}</pre>"
    )
    _telegram_send(bot_token, chat_id, msg)
