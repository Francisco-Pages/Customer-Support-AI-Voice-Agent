"""
ClickSend inbound SMS webhook.

Receives inbound SMS messages from ClickSend and relays them to the active
call session via the Redis sms_inbound:{phone} pub/sub channel — the same
channel that the agent's _watch_sms task is subscribed to.

ClickSend does not sign webhook payloads, so there is no signature to verify.
To add a layer of security, set CLICKSEND_WEBHOOK_SECRET and append it as a
query parameter when registering the webhook URL in ClickSend:
    https://your-domain.com/clicksend/webhook?secret=YOUR_SECRET

Inbound payload fields used:
    from   — sender E.164 phone number
    body   — message text
    to     — recipient number (your ClickSend number)
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.config import settings
from app.dependencies import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clicksend", tags=["ClickSend"])


@router.post("/webhook")
async def clicksend_webhook(
    request: Request,
    secret: str | None = Query(default=None),
):
    """
    Receives inbound SMS events from ClickSend and forwards them to the
    active agent session via Redis pub/sub.
    """
    # Optional shared-secret check (query param appended to the webhook URL)
    if settings.clicksend_webhook_secret:
        if secret != settings.clicksend_webhook_secret:
            logger.warning("ClickSend webhook secret mismatch — rejecting request")
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.debug("ClickSend webhook payload | %s", str(payload)[:1000])

    sender_phone: str = payload.get("from", "")
    body: str = payload.get("body", "").strip()

    if not sender_phone or not body:
        logger.warning(
            "ClickSend webhook missing sender or body | sender=%r body=%r",
            sender_phone,
            body[:80],
        )
        return Response(status_code=204)

    logger.info("Inbound ClickSend SMS | from=%s body=%r", sender_phone, body[:80])

    try:
        redis = await get_redis()

        if await redis.exists(f"active_call:{sender_phone}"):
            await redis.publish(f"sms_inbound:{sender_phone}", body)
            logger.info("ClickSend SMS relayed to active session | from=%s", sender_phone)
        else:
            logger.info("ClickSend SMS from %s ignored — no active call", sender_phone)
    except Exception:
        logger.warning("Redis error handling inbound ClickSend SMS", exc_info=True)

    return Response(status_code=204)
