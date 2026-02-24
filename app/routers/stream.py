"""
WebSocket endpoints for Twilio Media Streams.

Twilio streams μ-law 8kHz audio as base64-encoded chunks inside JSON messages.
These endpoints receive that audio and bridge it to the LiveKit agent pipeline.

Twilio Media Stream message types:
  connected — WebSocket handshake confirmation
  start     — Stream metadata (stream SID, call SID, custom parameters)
  media     — Audio payload (base64 mulaw, 8kHz, mono)
  stop      — Stream ended
"""

import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["Stream"])


# ---------------------------------------------------------------------------
# Inbound stream
# ---------------------------------------------------------------------------

@router.websocket("/inbound")
async def inbound_stream(websocket: WebSocket):
    """
    Bridges a Twilio inbound call Media Stream to the LiveKit agent pipeline.

    Flow:
    1. Accept the WebSocket connection from Twilio
    2. Parse the `start` event to extract call metadata and customer phone number
    3. Initialise a LiveKit agent session for this call
    4. Forward incoming audio chunks to LiveKit STT
    5. Receive TTS audio from LiveKit and send back to Twilio
    6. Clean up on disconnect

    TODO: Implement LiveKit session initialisation and audio bridging.
    """
    await websocket.accept()
    logger.info("Inbound Media Stream WebSocket connected")

    call_sid: str | None = None
    caller: str | None = None

    try:
        async for raw_message in websocket.iter_text():
            message = json.loads(raw_message)
            event = message.get("event")

            if event == "connected":
                logger.info("Twilio Media Stream connected | protocol=%s", message.get("protocol"))

            elif event == "start":
                stream_sid = message["start"]["streamSid"]
                call_sid = message["start"]["callSid"]
                custom_params = message["start"].get("customParameters", {})
                caller = custom_params.get("caller")

                logger.info(
                    "Stream started | StreamSid=%s CallSid=%s Caller=%s",
                    stream_sid,
                    call_sid,
                    caller,
                )

                # TODO: Look up or create customer record by caller phone number
                # TODO: Initialise LiveKit agent session for this call
                # await livekit_bridge.start_inbound_session(
                #     websocket=websocket,
                #     call_sid=call_sid,
                #     caller=caller,
                #     stream_sid=stream_sid,
                # )

            elif event == "media":
                # Audio payload: base64-encoded μ-law 8kHz mono
                payload = message["media"]["payload"]
                audio_chunk = base64.b64decode(payload)

                # TODO: Forward audio_chunk to LiveKit STT pipeline
                _ = audio_chunk

            elif event == "stop":
                logger.info("Stream stopped | CallSid=%s", call_sid)
                # TODO: Signal LiveKit session to finalise (save transcript, summary)
                break

    except WebSocketDisconnect:
        logger.info("Twilio Media Stream disconnected | CallSid=%s", call_sid)
    except Exception:
        logger.exception("Unhandled error in inbound stream | CallSid=%s", call_sid)
    finally:
        # TODO: Ensure LiveKit session is torn down and call record is persisted
        logger.info("Inbound stream handler exiting | CallSid=%s", call_sid)


# ---------------------------------------------------------------------------
# Outbound stream
# ---------------------------------------------------------------------------

@router.websocket("/outbound")
async def outbound_stream(websocket: WebSocket):
    """
    Bridges a Twilio outbound call Media Stream to the LiveKit agent pipeline.

    Identical protocol to the inbound stream; uses an outbound-specific
    system prompt and campaign payload injected by the start event parameters.

    TODO: Implement LiveKit session initialisation and audio bridging.
    """
    await websocket.accept()
    logger.info("Outbound Media Stream WebSocket connected")

    call_sid: str | None = None
    callee: str | None = None

    try:
        async for raw_message in websocket.iter_text():
            message = json.loads(raw_message)
            event = message.get("event")

            if event == "connected":
                logger.info("Outbound Media Stream connected")

            elif event == "start":
                stream_sid = message["start"]["streamSid"]
                call_sid = message["start"]["callSid"]
                custom_params = message["start"].get("customParameters", {})
                callee = custom_params.get("callee")

                logger.info(
                    "Outbound stream started | StreamSid=%s CallSid=%s Callee=%s",
                    stream_sid,
                    call_sid,
                    callee,
                )

                # TODO: Load customer record and campaign payload
                # TODO: Initialise LiveKit outbound agent session
                # await livekit_bridge.start_outbound_session(
                #     websocket=websocket,
                #     call_sid=call_sid,
                #     callee=callee,
                #     stream_sid=stream_sid,
                # )

            elif event == "media":
                payload = message["media"]["payload"]
                audio_chunk = base64.b64decode(payload)

                # TODO: Forward audio_chunk to LiveKit STT pipeline
                _ = audio_chunk

            elif event == "stop":
                logger.info("Outbound stream stopped | CallSid=%s", call_sid)
                break

    except WebSocketDisconnect:
        logger.info("Outbound Media Stream disconnected | CallSid=%s", call_sid)
    except Exception:
        logger.exception("Unhandled error in outbound stream | CallSid=%s", call_sid)
    finally:
        logger.info("Outbound stream handler exiting | CallSid=%s", call_sid)
