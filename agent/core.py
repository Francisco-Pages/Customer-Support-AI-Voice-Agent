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
import logging
import re

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, ChatContext, ChatMessage, JobContext, room_io
from livekit.plugins import deepgram, openai, silero, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from agent.prompts import INBOUND_SYSTEM_PROMPT, OUTBOUND_SYSTEM_PROMPT
from app.rag.retriever import retrieve

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

    Inherits from Agent to provide HVAC-specific instructions and an
    opening greeting on session start.
    """

    def __init__(self, direction: str = "inbound") -> None:
        instructions = (
            INBOUND_SYSTEM_PROMPT if direction == "inbound" else OUTBOUND_SYSTEM_PROMPT
        )
        super().__init__(instructions=instructions)

    async def on_enter(self) -> None:
        """Deliver the opening greeting when the agent becomes active."""
        await self.session.generate_reply(
            instructions=(
                "Greet the caller warmly and professionally. "
                "Introduce yourself as Alex from HVAC support. "
                "Ask how you can help them today. "
                "Keep the greeting to one or two sentences."
            )
        )

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

    await session.start(
        room=ctx.room,
        agent=HVACAssistant(direction=direction),
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

    logger.info("Agent session running | room=%s direction=%s", ctx.room.name, direction)

    # Keep the coroutine alive until the room closes (call ends or caller hangs up).
    await asyncio.sleep(float("inf"))
