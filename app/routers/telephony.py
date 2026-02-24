"""
Twilio webhook endpoints.

/inbound  — Called by Twilio when a customer dials in. Returns TwiML that opens
            a Media Stream WebSocket for the LiveKit pipeline.
/outbound — Called by Twilio when an outbound call is answered. Returns TwiML
            to start the outbound agent session.
/status   — Receives call status events from Twilio (completed, failed, etc.)
            and persists the final call record.
"""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, Start, Stream, VoiceResponse

from app.config import settings
from app.core.security import validate_twilio_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telephony", tags=["Telephony"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _twiml_response(twiml: VoiceResponse) -> Response:
    return Response(content=str(twiml), media_type="application/xml")


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

    Responds with TwiML that:
    1. Opens a bi-directional Media Stream WebSocket to /stream/inbound
    2. Keeps the call alive while the LiveKit agent pipeline handles audio
    """
    body = dict(await request.form())
    validate_twilio_signature(request, body)

    logger.info("Inbound call received | CallSid=%s From=%s", CallSid, From)

    stream_url = settings.app_base_url.rstrip("/") + "/stream/inbound"

    response = VoiceResponse()
    start = Start()
    stream = Stream(url=stream_url)
    stream.parameter(name="call_sid", value=CallSid)
    stream.parameter(name="caller", value=From)
    start.append(stream)
    response.append(start)

    # <Pause> keeps the call open while the WebSocket session runs.
    # Duration is set to the Twilio max; the agent will end the call programmatically.
    response.pause(length=120)

    return _twiml_response(response)


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

    Responds with TwiML that opens a Media Stream for the outbound agent session.
    The campaign type and customer context are passed as Stream parameters so the
    LiveKit agent can load the correct prompt and payload.
    """
    body = dict(await request.form())
    validate_twilio_signature(request, body)

    logger.info("Outbound call answered | CallSid=%s To=%s", CallSid, To)

    stream_url = settings.app_base_url.rstrip("/") + "/stream/outbound"

    response = VoiceResponse()
    start = Start()
    stream = Stream(url=stream_url)
    stream.parameter(name="call_sid", value=CallSid)
    stream.parameter(name="callee", value=To)
    start.append(stream)
    response.append(start)
    response.pause(length=120)

    return _twiml_response(response)


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
    Twilio posts call lifecycle events here (initiated, ringing, in-progress,
    completed, busy, failed, no-answer).

    On completion this handler should persist the final call record.
    TODO: write final duration and status to the calls table in PostgreSQL.
    """
    body = dict(await request.form())
    validate_twilio_signature(request, body)

    logger.info(
        "Call status update | CallSid=%s Status=%s Duration=%ss",
        CallSid,
        CallStatus,
        CallDuration,
    )

    # TODO: Update calls table with final status and duration
    # await call_service.finalize_call(CallSid, CallStatus, int(CallDuration))

    return Response(status_code=204)
