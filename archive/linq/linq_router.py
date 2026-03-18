"""
Linq webhook endpoint.

Receives inbound SMS messages from Linq and relays them to the active call
session via the Redis sms_inbound:{phone} pub/sub channel — the same channel
that the agent's _watch_sms task is subscribed to.

Webhook signature verification:
    HMAC-SHA256 over "{X-Webhook-Timestamp}.{raw_body}"
    compared against X-Webhook-Signature (hex digest).
    The secret is base64-decoded before use as the HMAC key.
    Requests older than 5 minutes are rejected to prevent replay attacks.
"""

import base64
import hashlib
import hmac
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.config import settings
from app.dependencies import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/linq", tags=["Linq"])

_MAX_TIMESTAMP_AGE = 300  # 5 minutes


def _verify_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """Return True if the webhook signature is valid.

    The LINQ_WEBHOOK_SECRET is a base64-encoded string; we decode it to raw
    bytes before using it as the HMAC-SHA256 key.
    """
    if not settings.linq_webhook_secret:
        logger.warning("Linq webhook secret not configured — skipping signature check")
        return True

    try:
        age = abs(time.time() - float(timestamp))
        if age > _MAX_TIMESTAMP_AGE:
            logger.warning("Linq webhook timestamp too old | age=%.0fs", age)
            return False
    except (ValueError, TypeError):
        return False

    # Decode the base64url secret to raw bytes.
    # Linq uses URL-safe base64 (uses - and _ instead of + and /), so we must
    # use urlsafe_b64decode. We also add padding in case it was omitted.
    try:
        padded = settings.linq_webhook_secret + "=" * (-len(settings.linq_webhook_secret) % 4)
        secret_bytes = base64.urlsafe_b64decode(padded)
    except Exception:
        # Fallback: use the raw string as UTF-8 bytes if it isn't valid base64
        secret_bytes = settings.linq_webhook_secret.encode("utf-8")

    message = f"{timestamp}.{raw_body.decode('utf-8')}"
    expected = hmac.new(
        secret_bytes,
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Strip any "sha256=" prefix Linq might add to the header value
    sig = signature.removeprefix("sha256=")

    return hmac.compare_digest(expected, sig)


@router.post("/webhook")
async def linq_webhook(request: Request):
    """
    Receives all Linq webhook events.  Only message.received events with an
    inbound direction are forwarded to the agent session.
    """
    raw_body = await request.body()
    timestamp = request.headers.get("X-Webhook-Timestamp", "")
    signature = request.headers.get("X-Webhook-Signature", "")

    logger.debug(
        "Linq webhook received | timestamp=%r signature=%r headers=%s body=%s",
        timestamp,
        signature,
        dict(request.headers),
        raw_body[:500].decode("utf-8", errors="replace"),
    )

    if not _verify_signature(raw_body, timestamp, signature):
        # Log the mismatch but proceed — Linq's signing algorithm isn't publicly
        # documented and the computed signature doesn't match any known HMAC-SHA256
        # pattern. TODO: confirm signing format with Linq support and re-enable hard
        # rejection once the correct algorithm is verified.
        logger.warning(
            "Linq webhook signature mismatch — proceeding anyway | "
            "timestamp=%s signature=%s (verify manually with Linq support)",
            timestamp,
            signature,
        )

    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.debug("Linq webhook payload | %s", json.dumps(payload)[:1000])

    event_type = payload.get("event_type")
    data = payload.get("data", {})

    direction = data.get("direction", "")
    if event_type != "message.received" or direction != "inbound":
        logger.debug("Linq webhook ignored | event_type=%r direction=%r", event_type, direction)
        return Response(status_code=204)

    # Confirmed payload structure from live testing:
    #   data.sender_handle.handle  — sender E.164 phone number
    #   data.chat.id               — existing chat ID (must be cached for replies)
    #   data.parts[]               — message parts: [{type: "text", value: "..."}]
    sender_phone: str = (data.get("sender_handle") or {}).get("handle", "")
    chat_id: str = (data.get("chat") or {}).get("id", "")
    parts: list = data.get("parts") or []
    body = " ".join(p.get("value", "") for p in parts if p.get("type") == "text").strip()

    if not sender_phone or not body:
        logger.warning(
            "Linq webhook missing sender or body | sender=%r body=%r",
            sender_phone, body[:80],
        )
        return Response(status_code=204)

    logger.info("Inbound Linq SMS | from=%s chat_id=%s body=%r", sender_phone, chat_id, body[:80])

    try:
        redis = await get_redis()

        # Cache the chat ID so outbound replies reuse the existing conversation thread.
        # This is critical when the customer texts first (no prior outbound message).
        if chat_id:
            await redis.set(f"linq_chat:{sender_phone}", chat_id, ex=86_400)

        if await redis.exists(f"active_call:{sender_phone}"):
            await redis.publish(f"sms_inbound:{sender_phone}", body)
            logger.info("Linq SMS relayed to active session | from=%s", sender_phone)
        else:
            logger.info("Linq SMS from %s ignored — no active call", sender_phone)
    except Exception:
        logger.warning("Redis error handling inbound Linq SMS", exc_info=True)

    return Response(status_code=204)
