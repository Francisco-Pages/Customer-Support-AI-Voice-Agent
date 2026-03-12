"""
Linq iMessage client.

Sends messages via the Linq Partner API v3 using iMessage (the number is
registered as an iMessage handle).  Linq uses a chat model:
the first message to a number creates a chat and returns a chatId; subsequent
messages are posted into that existing chat.  chatIds are cached in Redis
(key: linq_chat:{e164_phone}, TTL 24 h) to avoid an unnecessary GET round-trip
on every send.

Usage:
    from app.sms.linq_client import send_sms

    await send_sms(to="+15551234567", message="Your appointment is confirmed.")
"""

import logging

import httpx

from app.config import settings
from app.dependencies import get_redis

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.linqapp.com/api/partner/v3"
_CHAT_TTL = 86_400  # 24 hours


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.linq_api_token}",
        "Content-Type": "application/json",
    }


async def _get_cached_chat_id(phone: str) -> str | None:
    try:
        redis = await get_redis()
        return await redis.get(f"linq_chat:{phone}")
    except Exception:
        return None


async def _cache_chat_id(phone: str, chat_id: str) -> None:
    try:
        redis = await get_redis()
        await redis.set(f"linq_chat:{phone}", chat_id, ex=_CHAT_TTL)
    except Exception:
        logger.warning("Failed to cache Linq chatId for %s", phone)


async def send_sms(to: str, message: str) -> None:
    """
    Send an SMS to *to* (E.164) via Linq.

    Creates a new chat on first contact; reuses the cached chatId on subsequent
    messages.  Raises httpx.HTTPStatusError on API failures.
    """
    if not settings.linq_api_token or not settings.linq_from_number:
        raise RuntimeError("Linq credentials not configured (LINQ_API_TOKEN / LINQ_FROM_NUMBER)")

    chat_id = await _get_cached_chat_id(to)

    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10) as client:
        if chat_id:
            # Send into existing chat
            resp = await client.post(
                f"/chats/{chat_id}/messages",
                json={
                    "message": {
                        "parts": [{"type": "text", "value": message}],
                        "preferred_service": "iMessage",
                    }
                },
            )
        else:
            # Create chat + send first message
            resp = await client.post(
                "/chats",
                json={
                    "from": settings.linq_from_number,
                    "to": [to],
                    "message": {
                        "parts": [{"type": "text", "value": message}],
                        "preferred_service": "iMessage",
                    },
                },
            )

        logger.debug(
            "Linq API response | status=%s body=%s",
            resp.status_code,
            resp.text[:500],
        )
        resp.raise_for_status()
        data = resp.json()

        # Cache the chatId from the response
        new_chat_id = data.get("id") or (data.get("chat") or {}).get("id")
        if new_chat_id and new_chat_id != chat_id:
            await _cache_chat_id(to, new_chat_id)

    logger.info("Linq SMS sent | to=%s chat_id=%s", to, new_chat_id or chat_id)
