"""
ClickSend SMS client.

Sends SMS via the ClickSend REST API v3.  Authentication is HTTP Basic Auth
using the ClickSend account username and API key.  ClickSend is stateless —
there is no thread/chat concept, so each send is an independent request.

Usage:
    from app.sms.clicksend_client import send_sms

    await send_sms(to="+15551234567", message="Your appointment is confirmed.")
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://rest.clicksend.com/v3"


async def send_sms(to: str, message: str) -> None:
    """
    Send an SMS to *to* (E.164) via ClickSend.

    Raises httpx.HTTPStatusError on API failures.
    """
    if not settings.clicksend_username or not settings.clicksend_api_key:
        raise RuntimeError(
            "ClickSend credentials not configured (CLICKSEND_USERNAME / CLICKSEND_API_KEY)"
        )

    payload = {
        "messages": [
            {
                "body": message,
                "to": to,
                "from": settings.clicksend_from_number or None,
            }
        ]
    }

    async with httpx.AsyncClient(base_url=_BASE_URL, timeout=10) as client:
        resp = await client.post(
            "/sms/send",
            json=payload,
            auth=(settings.clicksend_username, settings.clicksend_api_key),
        )

        logger.debug(
            "ClickSend API response | status=%s body=%s",
            resp.status_code,
            resp.text[:500],
        )
        resp.raise_for_status()

    logger.info("ClickSend SMS sent | to=%s", to)
