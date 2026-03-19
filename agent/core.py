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
import json
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
    AudioConfig,
    BackgroundAudioPlayer,
    BuiltinAudioClip,
    ChatContext,
    ChatMessage,
    JobContext,
    function_tool,
    room_io,
)
from openai import AsyncOpenAI
from livekit.plugins import deepgram, elevenlabs, openai, silero, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from sqlalchemy import select
from twilio.rest import Client as TwilioClient

from agent.prompts import build_inbound_prompt, OUTBOUND_SYSTEM_PROMPT
from app.config import settings
from app.db.models import CustomerProduct
from app.dependencies import AsyncSessionLocal
from app.rag.retriever import retrieve, _index as _rag_index, _oai as _rag_oai
from app.services import appointment as appointment_service
from app.services import call as call_service
from app.services import customer as customer_service
from app.services import geo as geo_service
from app.services import parts as parts_service
from app.services import warranty as warranty_service
from app.email.gmail_client import send_documents_email as _send_documents_email
from app.sms.clicksend_client import send_sms as _send_sms
from app.documents.catalog import get_documents_sms_text

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
        prompt_override: str | None = None,
    ) -> None:
        if direction == "inbound":
            instructions = prompt_override or build_inbound_prompt(settings.clicksend_from_number)
        else:
            instructions = OUTBOUND_SYSTEM_PROMPT
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
        self._customer_context: str | None = None  # Pre-loaded on on_enter for first-turn injection
        self._customer_context_injected: bool = False
        self._user_end_timestamps: list[datetime] = []    # VAD end-of-speech, one per user turn
        self._agent_start_timestamps: list[datetime] = [] # TTS audio start, one per agent turn

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

        # Pre-load customer record so the LLM knows who is calling from turn 1.
        greeting = "Hi! Thank you for calling Comfortside customer support. How can I help you today?"
        if self._caller_phone:
            try:
                async with AsyncSessionLocal() as db:
                    customer = await customer_service.get_by_phone_with_products(db, self._caller_phone)
                    if customer:
                        lines = [
                            f"[CALLER CONTEXT — pre-loaded, do NOT call lookup_customer again]",
                            f"Name: {customer.name or 'Unknown'}",
                            f"Phone: {customer.phone}",
                        ]
                        if customer.address:
                            lines.append(f"Address: {customer.address}")
                        if customer.products:
                            product_strs = [
                                f"{p.product_model} ({p.product_line})"
                                + (f" — SN: {p.serial_number}" if p.serial_number else "")
                                + (f" — Warranty expires: {p.warranty_end_date.strftime('%Y-%m-%d')}" if p.warranty_end_date else "")
                                for p in customer.products
                            ]
                            lines.append("Registered products: " + "; ".join(product_strs))
                        _, recent_calls = await call_service.list_calls(db, customer_id=customer.id, limit=3)
                        if recent_calls:
                            call_lines = [
                                f"  [{c.started_at.strftime('%Y-%m-%d') if c.started_at else 'unknown'}] "
                                f"({c.resolution or 'unresolved'}): {c.summary or 'No summary.'}"
                                for c in recent_calls
                            ]
                            lines.append("Recent call history:\n" + "\n".join(call_lines))
                        self._customer_context = "\n".join(lines)
                        if customer.name:
                            first_name = customer.name.split()[0]
                            greeting = f"Welcome back, {first_name}! Thank you for calling Comfortside customer support. How can I help you today?"
            except Exception:
                logger.warning("Customer pre-load failed — continuing without context", exc_info=True)

        await self.session.say(greeting, allow_interruptions=False)

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
        user_idx = 0
        agent_idx = 0
        for msg in self.session.history.messages():
            if msg.role == "user":
                text = msg.text_content
                if text:
                    if user_idx < len(self._user_end_timestamps):
                        ts = self._user_end_timestamps[user_idx].strftime("%H:%M:%S")
                    else:
                        ts = datetime.fromtimestamp(msg.created_at, tz=timezone.utc).strftime("%H:%M:%S")
                    user_idx += 1
                    lines.append(f"[{ts}] Customer: {text}")
            elif msg.role == "assistant":
                text = msg.text_content
                if text:
                    if agent_idx < len(self._agent_start_timestamps):
                        ts = self._agent_start_timestamps[agent_idx].strftime("%H:%M:%S")
                    else:
                        ts = datetime.fromtimestamp(msg.created_at, tz=timezone.utc).strftime("%H:%M:%S")
                    agent_idx += 1
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

    # async def tts_node(
    #     self,
    #     text: AsyncIterable[str],
    #     model_settings,
    # ) -> AsyncGenerator[rtc.AudioFrame, None]:
    #     """Strip markdown characters the LLM may emit before sending to TTS."""
    #
    #     async def _clean(source: AsyncIterable[str]) -> AsyncGenerator[str, None]:
    #         async for chunk in source:
    #             # Remove bold/italic markers and backticks; strip leading '#' headers
    #             chunk = re.sub(r"[*`]", "", chunk)
    #             chunk = re.sub(r"(?m)^#+\s*", "", chunk)
    #             if chunk:
    #                 yield chunk
    #
    #     async for frame in Agent.default.tts_node(self, _clean(text), model_settings):
    #         yield frame

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
        # Inject pre-loaded customer context on the first turn so the LLM
        # knows who is calling without needing to call lookup_customer.
        if not self._customer_context_injected and self._customer_context:
            turn_ctx.add_message(role="system", content=self._customer_context)
            self._customer_context_injected = True

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
        Returns their name, address, registered products, and recent call history.
        Call this at the start of every inbound call to personalise the conversation.
        """
        recent_calls: list = []
        async with AsyncSessionLocal() as db:
            customer = await customer_service.get_by_phone_with_products(db, phone)
            if customer:
                _, recent_calls = await call_service.list_calls(
                    db, customer_id=customer.id, limit=3
                )

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

        if recent_calls:
            call_lines = []
            for c in recent_calls:
                date = c.started_at.strftime("%Y-%m-%d") if c.started_at else "unknown date"
                summary = c.summary or "No summary."
                resolution = c.resolution or "unresolved"
                call_lines.append(f"  [{date}] ({resolution}): {summary}")
            lines.append("Recent call history:\n" + "\n".join(call_lines))

        return "\n".join(lines)

    @function_tool
    async def save_customer_info(
        self,
        name: Annotated[str, "Caller's name — first name, or first and last name"],
        caller_type: Annotated[str | None, "Type of caller: 'owner' (product owner/homeowner) or 'technician' (HVAC technician or installer)"] = None,
        email: Annotated[str | None, "Caller's email address, if they provided it"] = None,
    ) -> str:
        """
        Save or update the caller's name, type, and optionally email in the customer database.

        Call this immediately after the caller tells you their name for the first time.
        Also call it any time the caller provides or corrects their email address, or
        when you determine whether they are an owner or a technician.
        This ensures the caller is recognised by name on future calls.
        """
        if not self._caller_phone:
            return "Cannot save customer info — caller phone number not available."

        async with AsyncSessionLocal() as db:
            customer, created = await customer_service.get_or_create(db, self._caller_phone)
            await customer_service.update(db, customer.id, name=name, email=email or None, caller_type=caller_type or None)
            if self._twilio_call_sid:
                await call_service.link_customer(db, self._twilio_call_sid, customer.id)
            await db.commit()

        action = "created" if created else "updated"
        result = f"Customer record {action} — name: {name}"
        if caller_type:
            result += f", type: {caller_type}"
        if email:
            result += f", email: {email}"
        return result

    @function_tool
    async def lookup_warranty(
        self,
        serial_number: Annotated[
            str, "Product serial number to check warranty status for"
        ],
    ) -> str:
        """
        Check the warranty status for a product by its serial number.
        Looks up the live Cooper & Hunter warranty database and returns
        whether the unit is registered, the purchase/installation dates,
        and the product name.
        """
        try:
            result = await warranty_service.lookup_warranty(serial_number)
        except Exception as exc:
            logger.warning("Warranty scrape failed for %s: %s", serial_number, exc)
            return (
                f"I wasn't able to reach the warranty database right now. "
                "Please ask the customer to check their warranty status at "
                "cooperandhunter.us/warranty or call back later."
            )

        if not result.found:
            return f"Serial number {serial_number!r} was not found in the Cooper & Hunter warranty database. Please double-check the serial number with the customer."

        lines = [f"Serial number: {result.serial_number}"]
        if result.product_title:
            lines.append(f"Product: {result.product_title}")
        lines.append(f"Registered: {'Yes' if result.is_registered else 'No'}")
        if result.purchase_date:
            lines.append(f"Purchase date: {result.purchase_date}")
        if result.installation_date:
            lines.append(f"Installation date: {result.installation_date}")
        if result.status_text:
            lines.append(f"Details: {result.status_text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Function tools — parts
    # ------------------------------------------------------------------

    @function_tool
    async def check_parts_availability(
        self,
        product_model: Annotated[
            str,
            "The customer's HVAC unit model number, e.g. 'MSEABU-09HRFN1-QRD0G-P'",
        ],
        part_type: Annotated[
            str | None,
            "Type of part needed, e.g. 'Fan Motor', 'Capacitor'. Omit if unknown.",
        ] = None,
        part_name: Annotated[
            str | None,
            "Specific part name if the customer mentioned one, e.g. 'Brushless DC motor'. Omit if unknown.",
        ] = None,
    ) -> str:
        """
        Look up the part number for a replacement part compatible with the
        customer's HVAC unit. Product model is required; part type and part
        name narrow the results when provided.
        """
        async with AsyncSessionLocal() as db:
            matches = await parts_service.lookup_parts(
                db,
                product_model=product_model,
                part_type=part_type,
                part_name=part_name,
            )

        if not matches:
            return (
                f"No parts found in our catalog for model '{product_model}'"
                + (f" — {part_type}" if part_type else "")
                + ". I can transfer you to a specialist who can check further."
            )

        # Deduplicate by part_number (same part may match via multiple model variants).
        seen: set[str] = set()
        unique = []
        for m in matches:
            if m["part_number"] not in seen:
                seen.add(m["part_number"])
                unique.append(m)

        def _price_str(m: dict) -> str:
            if m.get("dp") is not None and m.get("ndp") is not None:
                return f" | DP: ${m['dp']:.2f}, NDP: ${m['ndp']:.2f}"
            if m.get("ndp") is not None:
                return f" | Price: ${m['ndp']:.2f}"
            return ""

        _next_step = (
            "\n\nMANDATORY NEXT STEP: Do NOT read the part information aloud yet. "
            "First ask the caller: \"I found the part information. Would you prefer I text it to you, "
            "or would you like me to read it out loud?\" Wait for their answer before doing anything else."
        )

        if len(unique) == 1:
            m = unique[0]
            return (
                f"The replacement {m['part_type']} ({m['part_name']}) "
                f"for model '{product_model}' "
                f"has part number {m['part_number']}{_price_str(m)}."
                + _next_step
            )

        lines = [
            f"Found {len(unique)} compatible parts for '{product_model}':"
        ]
        for m in unique:
            lines.append(f"  • {m['part_number']} — {m['part_name']} ({m['part_type']}){_price_str(m)}")
        lines.append(_next_step)
        return "\n".join(lines)

    @function_tool
    async def get_part_by_number(
        self,
        part_number: Annotated[str, "The exact part number to look up, e.g. '11103020000179'"],
    ) -> str:
        """
        Look up a part's name, type, and pricing directly by its part number.
        Use this when the caller already has a part number and wants to know
        the price, description, or other details.
        """
        async with AsyncSessionLocal() as db:
            part = await parts_service.get_part_by_number(db, part_number)

        if not part:
            return f"Part number '{part_number}' was not found in our catalog."

        price = _price_str(part)
        return (
            f"Part {part['part_number']}: {part['part_name']} "
            f"({part['part_type']}){price}."
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
        Call this tool immediately — do not say anything first. The tool speaks
        the farewell to the caller automatically.
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
            await redis.set(
                f"transfer:{call_sid}",
                json.dumps({"to": settings.transfer_phone_number, "from": caller_phone}),
                ex=300,
            )
            await redis.aclose()
        except Exception:
            logger.warning(
                "Could not write transfer key to Redis | call_sid=%s", call_sid
            )

        # Speak the farewell directly via session.say() so we own the SpeechHandle.
        # This avoids any race between LLM response scheduling and our listener,
        # and ensures we await exactly this utterance — nothing else.
        farewell_handle = self.session.say(
            "I'm connecting you with a specialist now. Thank you for your patience, goodbye!",
            allow_interruptions=False,
        )

        async def _remove_sip_for_transfer() -> None:
            try:
                await asyncio.wait_for(asyncio.shield(farewell_handle._done_fut), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("Transfer farewell TTS timed out — removing SIP participant anyway")

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
            "The farewell has already been spoken. Do not say anything further."
        )

    @function_tool
    async def end_call(
        self,
        farewell_message: Annotated[
            str,
            "The exact farewell sentence to speak before hanging up. "
            "Keep it short and polite. Must be in the caller's language.",
        ],
    ) -> str:
        """
        End (hang up) the current call after speaking a farewell message.
        Use when: the caller asks to end the call, the conversation has concluded
        naturally, or the caller has been warned twice about inappropriate language
        and continues using it.
        Call this tool immediately — do not say anything before calling it.
        The tool speaks the farewell and hangs up automatically.
        """
        logger.info("end_call requested | farewell=%r", farewell_message)

        farewell_handle = self.session.say(farewell_message, allow_interruptions=False)

        room_name = self._room_name
        caller_phone = self._caller_phone

        async def _hang_up() -> None:
            try:
                await asyncio.wait_for(asyncio.shield(farewell_handle._done_fut), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("end_call farewell TTS timed out — hanging up anyway")

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
                    "SIP participant removed (call ended) | phone=%s room=%s",
                    caller_phone,
                    room_name,
                )
            except Exception as exc:
                logger.error(
                    "Failed to remove SIP participant on end_call | phone=%s error=%r",
                    caller_phone,
                    exc,
                )

        asyncio.ensure_future(_hang_up())

        return "Call termination initiated. The farewell has already been spoken. Do not say anything further."

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
        try:
            await _send_sms(to=customer_phone, message=message)
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

        try:
            await _send_sms(to=self._caller_phone, message=message)
        except Exception as exc:
            logger.error("SMS reply failed | to=%s error=%s", self._caller_phone, exc)
            return f"SMS reply could not be sent ({exc})."
        return f"SMS reply sent to {self._caller_phone}."

    # ------------------------------------------------------------------
    # Function tools — data deletion request
    # ------------------------------------------------------------------

    @function_tool
    async def request_data_deletion(self) -> str:
        """
        Flag the caller's record for deletion by the admin team.
        Does not delete data immediately — marks it for review on the dashboard.
        Use this when the caller explicitly asks to have their information removed.
        """
        if not self._caller_phone:
            return "Cannot process deletion request — caller phone number not available for this session."
        try:
            async with AsyncSessionLocal() as db:
                flagged = await customer_service.request_deletion(db, self._caller_phone)
                await db.commit()
        except Exception as exc:
            logger.error("Deletion request failed | phone=%s error=%s", self._caller_phone, exc)
            return "We were unable to submit your deletion request at this time. Please call back during business hours."

        if not flagged:
            return "No account was found for this phone number, so there is nothing to delete."
        return "Your deletion request has been submitted. Our team will remove your information within 30 days."

    # ------------------------------------------------------------------
    # Function tools — email documents
    # ------------------------------------------------------------------

    @function_tool
    async def send_documents_email(
        self,
        to_email: Annotated[
            str,
            "Customer email address to send documents to (e.g. john@example.com)",
        ],
        brand: Annotated[
            str,
            "Product brand — one of: 'Cooper and Hunter', 'Olmo', 'Bravo'",
        ],
        model: Annotated[
            str,
            "Product model name (e.g. 'Astoria', 'Multi-Zone', 'Olivia')",
        ],
    ) -> str:
        """
        Send an HTML email with product manuals, leaflets, and the brand catalog
        to the customer's email address.

        Use this when the caller asks for product documentation, manuals, spec
        sheets, or leaflets, and you have or can confirm their email address.
        Always confirm the email address with the caller before calling this tool.
        If the customer record has an email on file, confirm it rather than asking.
        """
        if not settings.gmail_sender or not settings.gmail_app_password:
            return (
                "Email sending is not configured on this system. "
                "Let the caller know you are unable to email documents at this time."
            )
        return await _send_documents_email(to_email, brand, model)

    @function_tool
    async def send_documents_sms(
        self,
        brand: Annotated[
            str,
            "Product brand — one of: 'Cooper and Hunter', 'Olmo', 'Bravo'",
        ],
        model: Annotated[
            str,
            "Product model name (e.g. 'Astoria', 'Multi-Zone', 'Olivia')",
        ],
    ) -> str:
        """
        Send the product document links as a plain-text SMS to the caller's phone.
        Use this when the caller prefers text over email.
        The links go to Google Drive where the manuals and leaflets are stored.
        """
        if not self._caller_phone:
            return "Cannot send SMS — caller phone number not available for this session."

        text = get_documents_sms_text(brand, model)
        if text is None:
            return (
                f"No documents found for {brand} {model}. "
                "Available brands: Cooper and Hunter, Olmo, Bravo."
            )

        try:
            await _send_sms(to=self._caller_phone, message=text)
        except Exception as exc:
            logger.error("Document SMS failed | to=%s error=%s", self._caller_phone, exc)
            return f"SMS could not be sent ({exc})."
        return f"Document links sent via SMS to {self._caller_phone}."

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
        def _fmt_entry(r: dict) -> str:
            s = f"Name: {r['name']} | Address: {r['address']} | Phone: {r['phone']}"
            if r.get("website"):
                s += f" | Website: {r['website']}"
            return s

        first = results[0]
        script = (
            f"Say: \"The first technician I found is {first['name']}. "
            f"Their phone number is {first['phone']}. "
            f"They are located at {first['address']}."
        )
        if first.get("website"):
            script += f" They also have a website at {first['website']}."
        script += ' Would you like another option?"'

        additional = [f"{i}. {_fmt_entry(r)}" for i, r in enumerate(results[1:], 2)]
        if additional:
            script += "\n\nADDITIONAL OPTIONS — read only one at a time, only if the caller asks for another:\n" + "\n".join(additional)
        script += "\n\nMANDATORY: After reading the first result, stop and ask: \"Would you like another option?\" Do not read more results unless the caller asks."
        return script

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

        def _fmt_entry(r: dict) -> str:
            s = f"Name: {r['name']} | Address: {r['address']} | Phone: {r['phone']}"
            if r.get("website"):
                s += f" | Website: {r['website']}"
            return s

        first = results[0]
        script = (
            f"Say: \"The first distributor I found is {first['name']}. "
            f"Their phone number is {first['phone']}. "
            f"They are located at {first['address']}."
        )
        if first.get("website"):
            script += f" They also have a website at {first['website']}."
        script += ' Would you like another option?"'

        additional = [f"{i}. {_fmt_entry(r)}" for i, r in enumerate(results[1:], 2)]
        if additional:
            script += "\n\nADDITIONAL OPTIONS — read only one at a time, only if the caller asks for another:\n" + "\n".join(additional)
        script += "\n\nMANDATORY: After reading the first result, stop and ask: \"Would you like another option?\" Do not read more results unless the caller asks."
        return script

    @function_tool
    async def switch_language(
        self,
        language: Annotated[
            str,
            "BCP-47 language code to switch speech recognition to, e.g. 'es' for Spanish, "
            "'fr' for French, 'pt' for Portuguese, 'en' for English",
        ],
    ) -> str:
        """
        Switch the speech recognition (STT) language when the caller wants to speak
        in a different language. Call this as soon as the caller asks to switch languages.
        """
        self.session.stt.update_options(language=language)
        logger.info("STT language switched to: %s", language)
        return f"Speech recognition switched to language: {language}. Please continue."

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
                handle = self.session.generate_reply(
                    user_input=f"[Customer sent via SMS]: {sms_body}",
                    chat_ctx=chat_ctx,
                    instructions=(
                        "This message arrived via SMS during the call. "
                        "Acknowledge it verbally and answer any question in it."
                    ),
                )

                # Wait for playout, shielded so cancellation doesn't abort the send.
                try:
                    await asyncio.shield(handle.wait_for_playout())
                except asyncio.CancelledError:
                    pass  # task cancelled but we still want to send the SMS below

                # Read the reply directly from the handle — more reliable than
                # session.history (avoids stale messages and post-activity race).
                reply_text: str | None = None
                for item in handle.chat_items:
                    if isinstance(item, ChatMessage) and item.role == "assistant":
                        t = item.text_content
                        if t:
                            reply_text = t
                            break

                logger.info("SMS reply | items=%d reply_text=%r", len(handle.chat_items), reply_text and reply_text[:80])

                if reply_text:
                    try:
                        await asyncio.shield(_send_sms(to=phone, message=reply_text[:1600]))
                        logger.info("SMS reply sent | to=%s", phone)
                    except Exception as exc:
                        logger.error("SMS reply failed | to=%s error=%r", phone, exc)
                else:
                    logger.warning("SMS reply skipped — no assistant text in handle | items=%s", handle.chat_items)
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

    # Pre-warm RAG clients so the first caller doesn't pay connection setup cost.
    try:
        _rag_index()
        _rag_oai()
    except Exception:
        logger.warning("RAG client pre-warm failed", exc_info=True)

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

    # Load runtime settings from Redis (set via admin dashboard).
    _prompt_override: str | None = None
    _temperature: float = 0.1
    _voice_id: str = "EXAVITQu4vr4xnSDxMaL"
    if direction == "inbound":
        try:
            _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            _prompt_override = await _redis.get("prompt:inbound")
            _stored = await _redis.hgetall("agent:settings")
            await _redis.aclose()
            if _prompt_override:
                logger.info("Using custom prompt from Redis (%d chars)", len(_prompt_override))
            if _stored.get("temperature"):
                _temperature = float(_stored["temperature"])
                logger.info("LLM temperature from Redis: %s", _temperature)
            if _stored.get("voice_id"):
                _voice_id = _stored["voice_id"]
                logger.info("TTS voice_id from Redis: %s", _voice_id)
        except Exception as _exc:
            logger.warning("Could not read settings from Redis: %s", _exc)

    # Build the voice pipeline session
    session = AgentSession(
        stt=deepgram.STT(model="nova-2-general", language="en"),
        llm=openai.LLM(model="gpt-4o-mini", temperature=_temperature),
        tts=elevenlabs.TTS(model="eleven_flash_v2_5", voice_id=_voice_id),  # Fast native multilingual TTS, 32 languages incl. Ukrainian
        vad=silero.VAD.load(),
        # turn_detection=MultilingualModel(),
    )

    # ------------------------------------------------------------------
    # Safety intercept — fires on every STT transcript before the LLM
    # processes it. If an emergency keyword is detected, cancel the
    # current LLM turn and deliver the hardcoded emergency response.
    # ------------------------------------------------------------------

    @session.on("user_stopped_speaking")
    def on_user_stopped_speaking() -> None:
        agent._user_end_timestamps.append(datetime.now(timezone.utc))

    @session.on("agent_started_speaking")
    def on_agent_started_speaking() -> None:
        agent._agent_start_timestamps.append(datetime.now(timezone.utc))

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
        if caller_phone:
            try:
                async with AsyncSessionLocal() as db:
                    await call_service.flag_safety_event(db, caller_phone)
                    await db.commit()
            except Exception:
                logger.warning("Could not flag safety event in DB | phone=%s", caller_phone, exc_info=True)

    # ------------------------------------------------------------------
    # Start the session
    # For SIP (Twilio telephony) participants, use BVCTelephony noise
    # cancellation which is tuned for narrowband 8kHz phone audio.
    # For regular WebRTC participants (e.g. playground testing), use BVC.
    # ------------------------------------------------------------------

    agent = HVACAssistant(
        direction=direction,
        caller_phone=caller_phone,
        room_name=ctx.room.name,
        prompt_override=_prompt_override,
    )
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

    # Play keyboard-typing sounds while the agent is in the "thinking" state
    # (during RAG retrieval + LLM generation). Two clips alternate randomly to
    # avoid repetition. No ambient sound — telephony callers find it distracting.
    background_audio = BackgroundAudioPlayer(
        thinking_sound=[
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.6),
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.5),
        ],
    )
    await background_audio.start(room=ctx.room, agent_session=session)

    # Give the agent a direct reference to close the session for transfers.
    agent._session_ref = session
    logger.info("Agent session running | room=%s direction=%s", ctx.room.name, direction)

    # Keep the coroutine alive until the room closes (call ends or caller hangs up).
    await asyncio.sleep(float("inf"))
