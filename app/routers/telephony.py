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

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import Dial, VoiceResponse

from app.config import settings
from app.core.security import validate_twilio_signature

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
):
    """
    Twilio calls this endpoint when a customer dials in.

    Returns TwiML that dials the LiveKit SIP server. LiveKit routes the
    call to a room and dispatches the hvac-support agent via the SIP
    dispatch rule configured with `lk sip dispatch create`.
    """
    body = dict(await request.form())
    validate_twilio_signature(request, body)

    logger.info("Inbound call | CallSid=%s From=%s To=%s", CallSid, From, To)

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
):
    """
    Twilio posts call lifecycle events here (completed, failed, busy, etc.).

    On completion this handler should persist the final call record.
    TODO: write final duration and status to the calls table in PostgreSQL.
    """
    body = dict(await request.form())
    validate_twilio_signature(request, body)

    logger.info(
        "Call status | CallSid=%s Status=%s Duration=%ss",
        CallSid,
        CallStatus,
        CallDuration,
    )

    # TODO: await call_service.finalize_call(CallSid, CallStatus, int(CallDuration))

    # Twilio calls this URL as the <Dial> action when the SIP leg ends.
    # It expects TwiML back — return an empty <Response> to hang up cleanly.
    return _twiml_response(VoiceResponse())
