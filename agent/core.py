"""
HVAC Voice AI Agent — LiveKit AgentServer entrypoint.

This module defines the AgentServer and the rtc_session entrypoint that
LiveKit dispatches one instance of per inbound or outbound call.

Architecture:
  Caller → Twilio PSTN → Twilio SIP trunk → LiveKit SIP server
         → LiveKit room → this agent (STT → GPT-4o → TTS) → back to caller

Run the worker from the project root:
    python run_agent.py dev       # development (hot-reload, connects to LiveKit)
    python run_agent.py start     # production

The worker connects to the LiveKit server specified by LIVEKIT_URL,
LIVEKIT_API_KEY, and LIVEKIT_API_SECRET environment variables.
"""

import asyncio
import contextlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, AsyncIterable, AsyncGenerator

import redis.asyncio as aioredis

from livekit import agents, api as lk_api, rtc
from livekit.agents import (
    AgentServer,
    AgentSession,
    Agent,
    ChatContext,
    ChatMessage,
    JobContext,
    function_tool,
    room_io,
)
from openai import AsyncOpenAI
from livekit.plugins import deepgram, openai, silero, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from sqlalchemy import select
from twilio.rest import Client as TwilioClient

from agent.prompts import INBOUND_SYSTEM_PROMPT, OUTBOUND_SYSTEM_PROMPT
from app.config import settings
from app.db.models import CustomerProduct
from app.dependencies import AsyncSessionLocal
from app.rag.retriever import retrieve
from app.services import appointment as appointment_service
from app.services import call as call_service
from app.services import customer as customer_service
from app.services import geo as geo_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety keyword detection
# Runs before the LLM — bypasses normal conversation for emergencies.
# ---------------------------------------------------------------------------

_SAFETY_RE = re.compile(
    r"\b("
    r"gas\s*leak|smell\s*gas|smells?\s*like\s*gas|"
    r"carbon\s*monoxide|co\s*detector|"
    r"there'?s\s*a\s*fire|house\s*is\s*on\s*fire|"
    r"electrical\s*hazard|electrical\s*fire|"
    r"smoke|explosion|exploded|"
    r"burning\s*smell|something'?s?\s*burning"
    r")\b",
    re.IGNORECASE,
)

_EMERGENCY_RESPONSE = (
    "This sounds like an emergency situation. "
    "Please hang up and call 911 immediately. "
    "Do not attempt to operate any equipment."
)


def _is_safety_emergency(text: str) -> bool:
    return bool(_SAFETY_RE.search(text))


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class HVACAssistant(Agent):
    """
    Alex — the HVAC customer support voice agent.

    Inherits from Agent to provide HVAC-specific instructions, an opening
    greeting on session start, Pattern 2 RAG injection on every user turn,
    and a full set of function tools the LLM can call during the conversation.
    """

    def __init__(
        self,
        direction: str = "inbound",
        caller_phone: str | None = None,
        room_name: str | None = None,
    ) -> None:
        instructions = (
            INBOUND_SYSTEM_PROMPT if direction == "inbound" else OUTBOUND_SYSTEM_PROMPT
        )
        super().__init__(instructions=instructions)
        self._twilio = TwilioClient(
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )
        self._caller_phone: str | None = caller_phone
        self._room_name: str | None = room_name
        self._twilio_call_sid: str | None = None
        self._sms_task: asyncio.Task | None = None
        self._session_ref: AgentSession | None = None  # Set by hvac_agent() after start

    # ------------------------------------------------------------------
    # Session lifecycle hooks
    # ------------------------------------------------------------------

    async def on_enter(self) -> None:
        """Deliver the opening greeting and start the SMS side-channel watcher."""
        # Only start the SMS watcher once — on_enter() can be called multiple times
        # by the framework (e.g. after reconnection), and each call would create a
        # new subscription that would receive every subsequent SMS.
        if self._caller_phone and not (self._sms_task and not self._sms_task.done()):
            try:
                redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
                await redis.set(f"active_call:{self._caller_phone}", "1", ex=7200)
                # Retrieve the Twilio Call SID stored by the /inbound webhook so
                # we can link the post-call transcript back to the DB record.
                self._twilio_call_sid = await redis.get(f"call_sid:{self._caller_phone}")
                await redis.aclose()
                self._sms_task = asyncio.create_task(
                    self._watch_sms(self._caller_phone)
                )
            except Exception:
                logger.warning("Redis unavailable — SMS side-channel disabled", exc_info=True)

        await self.session.generate_reply(
            instructions=(
                "Greet the caller warmly and professionally. "
                "Introduce yourself as Alex from HVAC support. "
                "Ask how you can help them today. "
                "Keep the greeting to one or two sentences."
            )
        )

    async def on_exit(self) -> None:
        """Cancel the SMS watcher, remove the active_call key, and save post-call data."""
        if self._sms_task:
            self._sms_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sms_task

        if self._caller_phone:
            try:
                redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
                await redis.delete(f"active_call:{self._caller_phone}")
                await redis.aclose()
            except Exception:
                logger.warning("Could not remove active_call key from Redis", exc_info=True)

        await self._save_post_call_data()

    async def _save_post_call_data(self) -> None:
        """Build transcript, generate summary, and write both to the calls table."""
        if not self._twilio_call_sid:
            logger.warning(
                "No Twilio Call SID available — post-call data not saved | phone=%s",
                self._caller_phone,
            )
            return

        try:
            transcript = self._build_transcript()
            summary = ""
            if transcript:
                try:
                    summary = await self._generate_summary(transcript)
                except Exception:
                    logger.warning("Summary generation failed", exc_info=True)

            async with AsyncSessionLocal() as db:
                await call_service.save_post_call_data(
                    db,
                    twilio_call_sid=self._twilio_call_sid,
                    transcript=transcript,
                    summary=summary,
                    livekit_room=self._room_name,
                )
                await db.commit()

            logger.info(
                "Post-call data saved | sid=%s transcript_chars=%d summary_chars=%d",
                self._twilio_call_sid,
                len(transcript),
                len(summary),
            )
        except Exception:
            logger.error("Failed to save post-call data", exc_info=True)

    def _build_transcript(self) -> str:
        """
        Reconstruct a readable transcript from the session chat history.
        Only includes user and assistant turns; skips system messages and
        RAG context injections.
        """
        lines = []
        for msg in self.session.history.messages():
            ts = datetime.fromtimestamp(msg.created_at, tz=timezone.utc).strftime("%H:%M:%S")
            if msg.role == "user":
                text = msg.text_content
                if text:
                    lines.append(f"[{ts}] Customer: {text}")
            elif msg.role == "assistant":
                text = msg.text_content
                if text:
                    lines.append(f"[{ts}] Alex: {text}")
        return "\n".join(lines)

    async def _generate_summary(self, transcript: str) -> str:
        """
        Call GPT-4o-mini to produce a 2-3 sentence summary of the call.
        Covers: customer's issue, what was resolved, and any next steps.
        """
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You summarize HVAC customer support call transcripts concisely "
                        "in 2-3 sentences. Cover: the customer's main issue, what was "
                        "resolved or offered, and any next steps such as appointments, "
                        "callbacks, parts orders, or escalations. Be specific and factual."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            max_tokens=200,
            temperature=0,
        )
        return response.choices[0].message.content or ""

    # ------------------------------------------------------------------
    # TTS pipeline node — sanitize LLM output before synthesis
    # ------------------------------------------------------------------

    async def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings,
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        """Strip markdown characters the LLM may emit before sending to TTS."""

        async def _clean(source: AsyncIterable[str]) -> AsyncGenerator[str, None]:
            async for chunk in source:
                # Remove bold/italic markers and backticks; strip leading '#' headers
                chunk = re.sub(r"[*`]", "", chunk)
                chunk = re.sub(r"(?m)^#+\s*", "", chunk)
                if chunk:
                    yield chunk

        async for frame in Agent.default.tts_node(self, _clean(text), model_settings):
            yield frame

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """
        Pattern 2 RAG injection — runs after the user's turn ends, before
        the LLM generates its response.

        Steps:
          1. Use the user's raw STT transcript as the Pinecone query.
          2. Embed + query Pinecone (Redis-cached for 1 hour).
          3. If relevant passages exist, inject them into turn_ctx as an
             assistant message so the LLM has grounded context for its answer.

        Injected messages are scoped to this turn only and are not persisted
        to the chat history, keeping the context window lean.
        """
        query = new_message.text_content
        if not query:
            return

        try:
            context = await retrieve(query=query)
        except Exception:
            logger.warning("RAG retrieval failed — continuing without context", exc_info=True)
            return

        if context:
            turn_ctx.add_message(
                role="assistant",
                content=(
                    "The following information from the HVAC knowledge base is relevant "
                    "to the customer's question. Use it to inform your answer, but speak "
                    "naturally — do not read it verbatim:\n\n"
                    f"{context}"
                ),
            )

    # ------------------------------------------------------------------
    # Function tools — customer & warranty
    # ------------------------------------------------------------------

    @function_tool
    async def lookup_customer(
        self,
        phone: Annotated[
            str, "Customer phone number in E.164 format (e.g. +15551234567)"
        ],
    ) -> str:
        """
        Look up a customer record by phone number.
        Returns their name, address, and registered products with warranty dates.
        Call this at the start of every inbound call to personalise the conversation.
        """
        async with AsyncSessionLocal() as db:
            customer = await customer_service.get_by_phone_with_products(db, phone)

        if not customer:
            return "No customer record found for that phone number."

        lines = [
            f"Name: {customer.name or 'Unknown'}",
            f"Phone: {customer.phone}",
        ]
        if customer.address:
            lines.append(f"Address: {customer.address}")

        if customer.products:
            product_strs = []
            for p in customer.products:
                s = f"{p.product_model} ({p.product_line})"
                if p.serial_number:
                    s += f" — SN: {p.serial_number}"
                if p.warranty_end_date:
                    s += f" — Warranty expires: {p.warranty_end_date.strftime('%Y-%m-%d')}"
                product_strs.append(s)
            lines.append("Registered products: " + "; ".join(product_strs))
        else:
            lines.append("No registered products on file.")

        return "\n".join(lines)

    @function_tool
    async def lookup_warranty(
        self,
        serial_number: Annotated[
            str, "Product serial number to check warranty status for"
        ],
    ) -> str:
        """
        Check the warranty status for a product by its serial number.
        Returns whether the warranty is active or expired and the expiry date.
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(CustomerProduct).where(
                    CustomerProduct.serial_number == serial_number.strip()
                )
            )
            product = result.scalar_one_or_none()

        if not product:
            return f"No product found with serial number {serial_number!r}."

        if product.warranty_end_date is None:
            return (
                f"Product {product.product_model} (SN: {serial_number}) — "
                "warranty expiry date not on file."
            )

        now = datetime.now(timezone.utc)
        exp = (
            product.warranty_end_date.replace(tzinfo=timezone.utc)
            if product.warranty_end_date.tzinfo is None
            else product.warranty_end_date
        )

        if exp >= now:
            days_left = (exp - now).days
            return (
                f"Product {product.product_model} (SN: {serial_number}) is under warranty. "
                f"Expires {exp.strftime('%B %d, %Y')} ({days_left} days remaining)."
            )
        return (
            f"Product {product.product_model} (SN: {serial_number}) — "
            f"warranty expired on {exp.strftime('%B %d, %Y')}."
        )

    # ------------------------------------------------------------------
    # Function tools — parts
    # ------------------------------------------------------------------

    @function_tool
    async def check_parts_availability(
        self,
        query: Annotated[
            str,
            "Part number, model number, or description of the part needed",
        ],
    ) -> str:
        """
        Check parts inventory for availability and compatibility with a given model.
        Returns stock status and estimated lead time.
        """
        # TODO: Implement once the parts_inventory table is added to the data layer.
        #       Query: SELECT * FROM parts_inventory WHERE part_number = $1
        #              OR $2 = ANY(compatible_with)
        return (
            "Parts inventory lookup is not yet connected in this system. "
            "I can transfer you to a specialist who can check availability directly."
        )

    # ------------------------------------------------------------------
    # Function tools — appointments
    # ------------------------------------------------------------------

    @function_tool
    async def create_appointment(
        self,
        customer_phone: Annotated[str, "Customer phone number in E.164 format"],
        appointment_type: Annotated[
            str,
            "Appointment type: 'service', 'installation', 'maintenance', or 'inspection'",
        ],
        scheduled_at_iso: Annotated[
            str,
            "Appointment date and time in ISO 8601 format (e.g. 2026-03-15T10:00:00)",
        ],
        notes: Annotated[
            str, "Description of the issue or any additional notes"
        ] = "",
    ) -> str:
        """
        Create a new service appointment for the customer.
        Always confirm the date, time, and type with the caller before calling this tool.
        """
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_iso)
        except ValueError:
            return (
                f"Invalid date format: {scheduled_at_iso!r}. "
                "Please use ISO 8601 (e.g. 2026-03-15T10:00:00)."
            )

        async with AsyncSessionLocal() as db:
            customer = await customer_service.get_by_phone(db, customer_phone)
            if not customer:
                return "Could not find a customer record for that phone number."
            appt = await appointment_service.create(
                db,
                customer_id=customer.id,
                appointment_type=appointment_type,
                scheduled_at=scheduled_at,
                notes=notes or None,
            )
            await db.commit()

        return (
            f"Appointment created. "
            f"Type: {appt.appointment_type}, "
            f"Scheduled: {appt.scheduled_at.strftime('%A, %B %d at %I:%M %p')}, "
            f"Reference ID: {appt.id}."
        )

    @function_tool
    async def update_appointment(
        self,
        appointment_id: Annotated[str, "UUID of the appointment to modify"],
        new_scheduled_at_iso: Annotated[
            str,
            "New date and time in ISO 8601 format — leave blank to keep unchanged",
        ] = "",
        new_status: Annotated[
            str,
            "New status — 'confirmed', 'cancelled', or 'completed' — leave blank to keep unchanged",
        ] = "",
        notes: Annotated[
            str, "Updated notes — leave blank to keep unchanged"
        ] = "",
    ) -> str:
        """
        Modify an existing appointment's date, status, or notes.
        Confirm the changes with the caller before calling this tool.
        """
        try:
            appt_id = uuid.UUID(appointment_id)
        except ValueError:
            return f"Invalid appointment ID: {appointment_id!r}."

        kwargs: dict = {}
        if new_scheduled_at_iso:
            try:
                kwargs["scheduled_at"] = datetime.fromisoformat(new_scheduled_at_iso)
            except ValueError:
                return f"Invalid date format: {new_scheduled_at_iso!r}."
        if new_status:
            kwargs["status"] = new_status
        if notes:
            kwargs["notes"] = notes

        if not kwargs:
            return "No changes specified — nothing was updated."

        async with AsyncSessionLocal() as db:
            appt = await appointment_service.update(db, appt_id, **kwargs)
            if not appt:
                return f"No appointment found with ID {appointment_id}."
            await db.commit()

        return (
            f"Appointment {appt.id} updated. "
            f"Scheduled: {appt.scheduled_at.strftime('%A, %B %d at %I:%M %p')}, "
            f"Status: {appt.status}."
        )

    # ------------------------------------------------------------------
    # Function tools — call history
    # ------------------------------------------------------------------

    @function_tool
    async def get_call_history(
        self,
        customer_phone: Annotated[str, "Customer phone number in E.164 format"],
    ) -> str:
        """
        Retrieve the last 5 call summaries for a customer.
        Use this to understand prior interactions and avoid asking the caller
        to repeat themselves.
        """
        async with AsyncSessionLocal() as db:
            customer = await customer_service.get_by_phone(db, customer_phone)
            if not customer:
                return "No customer record found for that phone number."
            _, calls = await call_service.list_calls(
                db, customer_id=customer.id, limit=5
            )

        if not calls:
            return "No previous call history on file."

        lines = []
        for c in calls:
            ts = c.started_at.strftime("%Y-%m-%d") if c.started_at else "unknown date"
            resolution = c.resolution or "unresolved"
            summary = c.summary or "No summary available."
            lines.append(f"{ts} [{resolution}]: {summary}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Function tools — escalation
    # ------------------------------------------------------------------

    @function_tool
    async def transfer_to_agent(
        self,
        reason: Annotated[
            str,
            "Brief reason for the transfer (e.g. 'billing dispute', 'complex repair question')",
        ],
    ) -> str:
        """
        Escalate the call to a live human specialist.
        Use when: the caller asks to speak to a person, the issue is outside your
        scope, or you have been unable to resolve the problem.
        Always tell the caller they are being transferred before this ends the session.
        """
        logger.info("Live transfer requested | reason=%r", reason)

        if not self._twilio_call_sid:
            logger.warning("transfer_to_agent called but no Twilio Call SID available")
            return (
                "Transfer could not be initiated — no active call SID found. "
                "Offer to schedule a callback instead."
            )

        call_sid = self._twilio_call_sid
        room_name = self._room_name
        caller_phone = self._caller_phone

        # Write the transfer intent to Redis.
        # When the SIP participant is removed below, LiveKit sends a SIP BYE to
        # Twilio. Twilio treats this as the called party hanging up, which fires
        # the <Dial> action URL (/telephony/status). That endpoint reads this key
        # and returns TwiML that bridges the caller to the human agent line.
        try:
            redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
            await redis.set(f"transfer:{call_sid}", settings.transfer_phone_number, ex=300)
            await redis.aclose()
        except Exception:
            logger.warning(
                "Could not write transfer key to Redis | call_sid=%s", call_sid
            )

        # After the farewell TTS plays (~8 s), remove the SIP participant from the
        # LiveKit room. This sends a SIP BYE to Twilio, which ends the <Dial> and
        # triggers the action URL — the correct path to bridge the caller.
        async def _remove_sip_for_transfer() -> None:
            await asyncio.sleep(8)
            try:
                async with lk_api.LiveKitAPI(
                    url=settings.livekit_url,
                    api_key=settings.livekit_api_key,
                    api_secret=settings.livekit_api_secret,
                ) as lk:
                    await lk.room.remove_participant(
                        lk_api.RoomParticipantIdentity(
                            room=room_name,
                            identity=f"sip_{caller_phone}",
                        )
                    )
                logger.info(
                    "SIP participant removed for transfer | phone=%s room=%s",
                    caller_phone,
                    room_name,
                )
            except Exception as exc:
                logger.error(
                    "Failed to remove SIP participant | phone=%s error=%r",
                    caller_phone,
                    exc,
                )

        asyncio.ensure_future(_remove_sip_for_transfer())

        return (
            f"Transfer to a live specialist has been initiated. Reason: {reason}. "
            "Say to the caller: 'I'm connecting you with a specialist right now — "
            "please hold for just a moment. Thank you for your patience.' "
            "Then say goodbye and wish them well. Do not say anything further after that."
        )

    @function_tool
    async def schedule_callback(
        self,
        customer_phone: Annotated[str, "Customer phone number in E.164 format"],
        preferred_time_iso: Annotated[
            str, "Caller's preferred callback time in ISO 8601 format"
        ],
        reason: Annotated[str, "Brief reason for the callback request"],
    ) -> str:
        """
        Schedule a callback from a human specialist at the customer's preferred time.
        Use this as the alternative to an immediate live transfer.
        """
        try:
            preferred_time = datetime.fromisoformat(preferred_time_iso)
        except ValueError:
            return (
                f"Invalid time format: {preferred_time_iso!r}. "
                "Please use ISO 8601 (e.g. 2026-03-15T14:00:00)."
            )

        async with AsyncSessionLocal() as db:
            customer = await customer_service.get_by_phone(db, customer_phone)
            if not customer:
                return "Could not find a customer record for that phone number."
            appt = await appointment_service.create(
                db,
                customer_id=customer.id,
                appointment_type="callback",
                scheduled_at=preferred_time,
                notes=f"Callback requested — reason: {reason}",
            )
            await db.commit()

        return (
            f"Callback scheduled for {preferred_time.strftime('%A, %B %d at %I:%M %p')}. "
            f"Reference ID: {appt.id}. "
            "A specialist will call back at that time."
        )

    # ------------------------------------------------------------------
    # Function tools — SMS
    # ------------------------------------------------------------------

    @function_tool
    async def send_appointment_sms(
        self,
        customer_phone: Annotated[
            str, "Customer phone number in E.164 format to send the SMS to"
        ],
        message: Annotated[
            str,
            "Full SMS text confirming the appointment — include date, time, and type",
        ],
    ) -> str:
        """
        Send an SMS appointment confirmation to the customer's phone.
        Call this after every appointment is created or updated.
        """
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self._twilio.messages.create(
                    body=message,
                    from_=settings.twilio_phone_number,
                    to=customer_phone,
                ),
            )
        except Exception as exc:
            logger.error("SMS send failed | to=%s error=%s", customer_phone, exc)
            return f"SMS could not be sent ({exc}). The appointment was still saved."
        return f"SMS confirmation sent to {customer_phone}."

    @function_tool
    async def reply_via_sms(
        self,
        message: Annotated[
            str,
            "The text to send back to the customer. Plain text only, no markdown.",
        ],
    ) -> str:
        """
        Send an SMS reply to the caller's phone number.
        Always call this when answering a question that arrived via text message,
        so the customer receives both a spoken answer and a written copy.
        """
        if not self._caller_phone:
            return "Cannot send SMS reply — caller phone number not available for this session."

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self._twilio.messages.create(
                    body=message,
                    from_=settings.twilio_phone_number,
                    to=self._caller_phone,
                ),
            )
        except Exception as exc:
            logger.error("SMS reply failed | to=%s error=%s", self._caller_phone, exc)
            return f"SMS reply could not be sent ({exc})."
        return f"SMS reply sent to {self._caller_phone}."

    # ------------------------------------------------------------------
    # Function tools — geo search
    # ------------------------------------------------------------------

    @function_tool
    async def search_technicians(
        self,
        city: Annotated[str, "City name the caller is located in (e.g. 'Austin')"],
        state: Annotated[
            str,
            "US state — two-letter code or full name (e.g. 'TX' or 'Texas')",
        ],
    ) -> str:
        """
        Find the 5 nearest certified HVAC technicians to the caller's location.
        Always ask the caller for their city and state before calling this tool.
        """
        results = await geo_service.search(city, state, record_type="technician")
        if not results:
            return (
                f"No certified technicians found near {city}, {state}. "
                "I can connect you with our main support line for further assistance."
            )
        lines = [f"Here are the 5 nearest certified technicians near {city}, {state}:"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. {r['name']} in {r['city']}, {r['state']} — {r['phone']}"
            )
        return "\n".join(lines)

    @function_tool
    async def search_distributors(
        self,
        city: Annotated[str, "City name the caller is located in (e.g. 'Austin')"],
        state: Annotated[
            str,
            "US state — two-letter code or full name (e.g. 'TX' or 'Texas')",
        ],
    ) -> str:
        """
        Find the 5 nearest authorized HVAC parts distributors near the caller's location.
        Always ask the caller for their city and state before calling this tool.
        """
        results = await geo_service.search(city, state, record_type="distributor")
        if not results:
            return (
                f"No authorized distributors found near {city}, {state}. "
                "I can connect you with our main support line for further assistance."
            )
        lines = [
            f"Here are the 5 nearest authorized distributors near {city}, {state}:"
        ]
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. {r['name']} in {r['city']}, {r['state']} — {r['phone']}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # SMS side-channel watcher (private)
    # ------------------------------------------------------------------

    async def _watch_sms(self, phone: str) -> None:
        """
        Subscribe to the sms_inbound:{phone} Redis pub/sub channel for the
        duration of the call and relay each incoming SMS into the session.

        Pub/sub requires a dedicated connection — a separate client is created
        here and closed when the task is cancelled via on_exit().

        On each message the agent is instructed to:
          1. Answer verbally (the normal voice response).
          2. Call reply_via_sms so the customer also gets a written copy.
        """
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"sms_inbound:{phone}")
        logger.info("SMS watcher active | channel=sms_inbound:%s", phone)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                sms_body: str = message["data"]
                logger.info("SMS received during call | from=%s body=%r", phone, sms_body)

                # RAG — same pattern as on_user_turn_completed but triggered
                # manually because generate_reply() bypasses that hook entirely.
                chat_ctx = self.session.history.copy()
                try:
                    rag_context = await retrieve(query=sms_body)
                    if rag_context:
                        chat_ctx.add_message(
                            role="assistant",
                            content=(
                                "The following information from the HVAC knowledge base "
                                "is relevant to the customer's question. Use it to inform "
                                "your answer, but speak naturally — do not read it verbatim:"
                                f"\n\n{rag_context}"
                            ),
                        )
                except Exception:
                    logger.warning("RAG retrieval failed for SMS", exc_info=True)

                # Pass as user_input so the framework adds it to the persistent
                # chat history via its normal scheduling path.
                await self.session.generate_reply(
                    user_input=f"[Customer sent via SMS]: {sms_body}",
                    chat_ctx=chat_ctx,
                    instructions=(
                        "This message arrived via SMS during the call. "
                        "Acknowledge it verbally and answer any question in it."
                    ),
                )

                # After playout, grab the agent's response from history and send
                # it as an SMS reply. We do this in code rather than asking the
                # LLM to call a tool — tool compliance is unreliable for this.
                try:
                    last_reply = next(
                        (m for m in reversed(self.session.history.messages()) if m.role == "assistant"),
                        None,
                    )
                    reply_text = last_reply.text_content if last_reply else None
                    logger.info("SMS reply | last_reply=%s text=%r", last_reply is not None, reply_text and reply_text[:80])
                    if reply_text:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None,
                            lambda: self._twilio.messages.create(
                                body=reply_text[:1600],
                                from_=settings.twilio_phone_number,
                                to=phone,
                            ),
                        )
                        logger.info("SMS reply sent | to=%s", phone)
                    else:
                        logger.warning("SMS reply skipped — no assistant text in history")
                except Exception as exc:
                    logger.error("SMS reply failed | to=%s error=%r", phone, exc)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(f"sms_inbound:{phone}")
            await redis.aclose()
            logger.info("SMS watcher stopped | channel=sms_inbound:%s", phone)


# ---------------------------------------------------------------------------
# Agent server & session entrypoint
# ---------------------------------------------------------------------------

server = AgentServer()


@server.rtc_session(agent_name="hvac-support")
async def hvac_agent(ctx: JobContext) -> None:
    """
    LiveKit dispatches one instance of this function per call.

    For SIP calls from Twilio, the caller appears as a SIP participant.
    Job metadata (set via dispatch rule or explicit dispatch) may include
    caller phone number, direction, and campaign type.
    """
    logger.info("Agent session starting | room=%s", ctx.room.name)

    # Determine call direction from job metadata (defaults to inbound)
    direction = "inbound"
    if ctx.job.metadata:
        import json
        try:
            meta = json.loads(ctx.job.metadata)
            direction = meta.get("direction", "inbound")
        except (json.JSONDecodeError, AttributeError):
            pass

    # Extract the caller's phone number from the room name.
    # LiveKit names SIP rooms: call-_{caller_e164}_{random}, e.g.
    #   call-_+19548025709_5kfzCTKWkP7W
    # This is available immediately — no need to wait for the SIP participant.
    _room_phone_re = re.compile(r"call-_(\+\d+)_")
    _m = _room_phone_re.search(ctx.room.name)
    caller_phone: str | None = _m.group(1) if _m else None
    logger.info("Caller phone | phone=%s room=%s", caller_phone, ctx.room.name)

    # Build the voice pipeline session
    session = AgentSession(
        stt=deepgram.STT(model="nova-2-phonecall"),   # Optimised for 8kHz phone audio
        llm=openai.LLM(model="gpt-4o-mini"),          # Lower latency than gpt-4o
        tts=deepgram.TTS(model="aura-2-thalia-en"),   # Much lower latency than OpenAI TTS
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    # ------------------------------------------------------------------
    # Safety intercept — fires on every STT transcript before the LLM
    # processes it. If an emergency keyword is detected, cancel the
    # current LLM turn and deliver the hardcoded emergency response.
    # ------------------------------------------------------------------

    @session.on("user_input_transcribed")
    def on_transcript(ev) -> None:
        transcript = getattr(ev, "transcript", "") or ""
        if transcript and _is_safety_emergency(transcript):
            logger.warning(
                "SAFETY EVENT detected | room=%s | transcript=%r",
                ctx.room.name,
                transcript,
            )
            asyncio.ensure_future(_handle_emergency(session))

    async def _handle_emergency(s: AgentSession) -> None:
        await s.generate_reply(
            instructions=(
                f"Immediately say the following, word for word, and nothing else: "
                f'"{_EMERGENCY_RESPONSE}"'
            )
        )

    # ------------------------------------------------------------------
    # Start the session
    # For SIP (Twilio telephony) participants, use BVCTelephony noise
    # cancellation which is tuned for narrowband 8kHz phone audio.
    # For regular WebRTC participants (e.g. playground testing), use BVC.
    # ------------------------------------------------------------------

    agent = HVACAssistant(direction=direction, caller_phone=caller_phone, room_name=ctx.room.name)
    await session.start(
        room=ctx.room,
        agent=agent,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    # Give the agent a direct reference to close the session for transfers.
    agent._session_ref = session
    logger.info("Agent session running | room=%s direction=%s", ctx.room.name, direction)

    # Keep the coroutine alive until the room closes (call ends or caller hangs up).
    await asyncio.sleep(float("inf"))
