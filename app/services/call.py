"""
Call service — create and finalize records in the calls table.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Call

logger = logging.getLogger(__name__)

# Twilio statuses that mean the call is permanently finished
_TERMINAL_STATUSES = {"completed", "failed", "busy", "no-answer", "canceled"}


async def create_call(
    db: AsyncSession,
    twilio_call_sid: str,
    direction: str,
    customer_id: uuid.UUID | None = None,
    livekit_room: str | None = None,
) -> Call:
    call = Call(
        twilio_call_sid=twilio_call_sid,
        direction=direction,
        customer_id=customer_id,
        livekit_room=livekit_room,
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    await db.flush()
    return call


async def get_by_id(db: AsyncSession, call_id: uuid.UUID) -> Call | None:
    result = await db.execute(select(Call).where(Call.id == call_id))
    return result.scalar_one_or_none()


async def get_by_sid(db: AsyncSession, twilio_call_sid: str) -> Call | None:
    result = await db.execute(
        select(Call).where(Call.twilio_call_sid == twilio_call_sid)
    )
    return result.scalar_one_or_none()


async def finalize_call(
    db: AsyncSession,
    twilio_call_sid: str,
    twilio_status: str,
    duration_sec: int,
) -> Call | None:
    """
    Write the final duration, end timestamp, and resolution after a call ends.

    Twilio posts status events (completed, failed, busy, no-answer, canceled)
    to /telephony/status. We skip non-terminal statuses (ringing, in-progress)
    since the call isn't done yet.

    Resolution logic:
      - If the agent already set a resolution during the call, preserve it.
      - If not, derive it from the Twilio status: "completed" → "resolved",
        anything else → "abandoned".
    """
    if twilio_status not in _TERMINAL_STATUSES:
        return None

    call = await get_by_sid(db, twilio_call_sid)
    if not call:
        return None

    call.ended_at = datetime.now(timezone.utc)
    call.duration_sec = duration_sec

    if call.resolution is None:
        call.resolution = "resolved" if twilio_status == "completed" else "abandoned"

    await db.flush()
    return call


async def save_post_call_data(
    db: AsyncSession,
    twilio_call_sid: str,
    transcript: str,
    summary: str,
    livekit_room: str | None = None,
) -> Call | None:
    """
    Persist the full conversation transcript and GPT-generated summary
    after a call ends. Called from the agent's on_exit() hook.

    Also backfills livekit_room if it was not set at call creation time.
    """
    call = await get_by_sid(db, twilio_call_sid)
    if not call:
        logger.warning("save_post_call_data: no call record for SID %s", twilio_call_sid)
        return None

    call.transcript = transcript
    call.summary = summary
    if livekit_room and call.livekit_room is None:
        call.livekit_room = livekit_room

    await db.flush()
    return call


async def list_calls(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID | None = None,
    resolution: str | None = None,
    safety_event: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Call]]:
    """Return (total_count, page) ordered by started_at descending."""
    filters = []
    if customer_id is not None:
        filters.append(Call.customer_id == customer_id)
    if resolution is not None:
        filters.append(Call.resolution == resolution)
    if safety_event is not None:
        filters.append(Call.safety_event == safety_event)
    if date_from is not None:
        filters.append(Call.started_at >= date_from)
    if date_to is not None:
        filters.append(Call.started_at <= date_to)

    count_q = select(func.count()).select_from(Call)
    data_q = select(Call).order_by(Call.started_at.desc())

    for f in filters:
        count_q = count_q.where(f)
        data_q = data_q.where(f)

    total = (await db.execute(count_q)).scalar_one()
    rows = (await db.execute(data_q.limit(limit).offset(offset))).scalars().all()

    return total, list(rows)
