"""
Twilio webhook endpoints.

/inbound  — Called by Twilio when a customer dials in. Returns TwiML that
            dials the LiveKit SIP server, connecting the caller to a room
            where the AI agent is waiting.

/outbound — Called by Twilio when an outbound call is answered. Returns
            TwiML to connect the answered call to a LiveKit SIP room.

/status   — Receives call status events from Twilio (completed, failed, etc.)
            and persists the final call record.

SIP Integration overview:
  Caller → Twilio PSTN → our /inbound webhook → TwiML <Dial><Sip>
         → LiveKit SIP server → LiveKit room → hvac-support agent
"""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.twiml.voice_response import Dial, VoiceResponse

from app.config import settings
from app.core.security import validate_twilio_signature
from app.dependencies import get_db, get_redis
from app.services import call as call_service
from app.services import customer as customer_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telephony", tags=["Telephony"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _twiml_response(twiml: VoiceResponse) -> Response:
    return Response(content=str(twiml), media_type="application/xml")


def _sip_twiml(phone_number: str) -> VoiceResponse:
    """
    Build TwiML that routes the call to LiveKit via SIP.

    The SIP URI format is:  sip:<phone_number>@<livekit_sip_host>
    LiveKit uses the phone number to match the inbound SIP trunk and
    dispatch the call to a room via the configured dispatch rule.
    """
    sip_uri = f"sip:{phone_number}@{settings.livekit_sip_host}"
    response = VoiceResponse()
    dial = Dial(
        # Answer supervision — Twilio waits for SIP 200 OK before billing
        answer_on_bridge=True,
        # Post-call status callback
        action=f"{settings.app_base_url.rstrip('/')}/telephony/status",
    )
    dial.sip(
        sip_uri,
        username=settings.sip_trunk_username,
        password=settings.sip_trunk_password,
    )
    response.append(dial)
    return response


# ---------------------------------------------------------------------------
# Inbound call webhook
# ---------------------------------------------------------------------------


@router.post("/inbound")
async def inbound_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    CallStatus: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Twilio calls this endpoint when a customer dials in.

    Returns TwiML that dials the LiveKit SIP server. LiveKit routes the
    call to a room and dispatches the hvac-support agent via the SIP
    dispatch rule configured with `lk sip dispatch create`.

    Also creates the call record in the DB and stores the Twilio Call SID
    in Redis (keyed by caller phone) so the agent can retrieve it on entry
    and link it to the LiveKit room / post-call transcript.
    """
    body = dict(await request.form())
    validate_twilio_signature(request, body)

    logger.info("Inbound call | CallSid=%s From=%s To=%s", CallSid, From, To)

    # Create the call record. Look up the customer so we can link the record
    # to an existing account; unknown callers get customer_id=None.
    try:
        customer = await customer_service.get_by_phone(db, From)
        await call_service.create_call(
            db,
            twilio_call_sid=CallSid,
            direction="inbound",
            customer_id=customer.id if customer else None,
        )
        # db.commit() is handled by the get_db dependency on a clean exit
    except Exception:
        logger.warning("Could not create call record | CallSid=%s", CallSid, exc_info=True)

    # Store CallSid in Redis so the agent can read it by caller phone in on_enter().
    # TTL matches the active_call key (2 hours) — more than enough for any call.
    try:
        redis = await get_redis()
        await redis.set(f"call_sid:{From}", CallSid, ex=7200)
    except Exception:
        logger.warning("Could not store call_sid in Redis | CallSid=%s", CallSid, exc_info=True)

    # Route to LiveKit using the dialled Twilio number (To) as the SIP identifier.
    # LiveKit's inbound trunk matches on this number.
    twiml = _sip_twiml(To)
    logger.info("Returning TwiML:\n%s", twiml)
    return _twiml_response(twiml)


# ---------------------------------------------------------------------------
# Outbound call webhook
# ---------------------------------------------------------------------------


@router.post("/outbound")
async def outbound_call(
    request: Request,
    CallSid: str = Form(...),
    To: str = Form(...),
    CallStatus: str = Form(...),
):
    """
    Twilio calls this endpoint when an outbound call is answered.

    Routes the answered call into a LiveKit SIP room so the outbound
    agent can take over the conversation.

    TODO: Wire up outbound SIP trunk (requires Elastic SIP Trunking on
    Twilio and a LiveKit outbound trunk). For v1 outbound testing, use
    LiveKit's SIP createCall API directly instead.
    """
    body = dict(await request.form())
    validate_twilio_signature(request, body)

    logger.info("Outbound call answered | CallSid=%s To=%s", CallSid, To)

    return _twiml_response(_sip_twiml(settings.twilio_phone_number))


# ---------------------------------------------------------------------------
# Call status callback
# ---------------------------------------------------------------------------


@router.post("/status")
async def call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str = Form(default="0"),
    DialCallStatus: str | None = Form(default=None),
    DialCallDuration: str = Form(default="0"),
    db: AsyncSession = Depends(get_db),
):
    """
    Handles two different Twilio callbacks on the same URL:

    1. <Dial> action callback — fired when the SIP leg ends (DialCallStatus present).
       If a transfer is pending (Redis key set by the agent), return TwiML that
       bridges the caller to the transfer number. Otherwise hang up cleanly.

    2. Terminal status callback — fired when the entire call ends (DialCallStatus
       absent, CallStatus is completed/failed/etc.). Persists the call record.
    """
    body = dict(await request.form())
    validate_twilio_signature(request, body)

    logger.info(
        "Call status | CallSid=%s Status=%s Duration=%ss DialCallStatus=%s",
        CallSid,
        CallStatus,
        CallDuration,
        DialCallStatus,
    )

    if DialCallStatus is not None:
        # <Dial> action callback — the SIP leg just ended.
        # Check whether the agent queued a transfer for this call.
        try:
            redis = await get_redis()
            transfer_number = await redis.get(f"transfer:{CallSid}")
            if transfer_number:
                await redis.delete(f"transfer:{CallSid}")
                response = VoiceResponse()
                response.dial(
                    transfer_number,
                    caller_id=settings.twilio_phone_number,
                    timeout=30,
                )
                twiml_str = str(response)
                logger.info(
                    "Bridging caller to transfer number | CallSid=%s to=%s twiml=%s",
                    CallSid,
                    transfer_number,
                    twiml_str,
                )
                return _twiml_response(response)
        except Exception:
            logger.warning(
                "Redis error checking transfer key | CallSid=%s", CallSid, exc_info=True
            )
        # No transfer pending — finalize the call record and hang up cleanly.
        await call_service.finalize_call(
            db,
            twilio_call_sid=CallSid,
            twilio_status=DialCallStatus,
            duration_sec=int(DialCallDuration),
        )
        return _twiml_response(VoiceResponse())

    # Terminal status callback — persist the final call record.
    await call_service.finalize_call(
        db,
        twilio_call_sid=CallSid,
        twilio_status=CallStatus,
        duration_sec=int(CallDuration),
    )
    return _twiml_response(VoiceResponse())


# ---------------------------------------------------------------------------
# Inbound SMS webhook
# ---------------------------------------------------------------------------


@router.post("/sms")
async def inbound_sms(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
):
    """
    Twilio posts incoming SMS messages here when a text is sent to our number.

    If the sender currently has an active voice call (tracked via the
    active_call:{phone} Redis key set by the agent on call start), the
    message body is published to the sms_inbound:{phone} pub/sub channel
    so the agent can answer verbally and reply by text.

    SMS from numbers with no active call are silently dropped — this
    endpoint is intentionally a side-channel for callers already on the line.
    """
    form = dict(await request.form())
    validate_twilio_signature(request, form)

    logger.info("Inbound SMS | from=%s body=%r", From, Body[:80])

    try:
        redis = await get_redis()
        if await redis.exists(f"active_call:{From}"):
            await redis.publish(f"sms_inbound:{From}", Body)
            logger.info("SMS relayed to active session | from=%s", From)
        else:
            logger.info("SMS from %s ignored — no active call", From)
    except Exception:
        logger.warning("Redis error handling inbound SMS", exc_info=True)

    # Twilio requires a response even for SMS webhooks.
    return Response(content="<Response/>", media_type="application/xml")
