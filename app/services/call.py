"""
Call service — create and finalize records in the calls table.
"""

import logging
import uuid
from dataclasses import dataclass
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
    caller_phone: str | None = None,
) -> Call:
    call = Call(
        twilio_call_sid=twilio_call_sid,
        direction=direction,
        customer_id=customer_id,
        livekit_room=livekit_room,
        caller_phone=caller_phone,
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
    resolution: str | None = None,
) -> Call | None:
    """
    Write the final duration, end timestamp, and resolution after a call ends.

    Twilio posts status events (completed, failed, busy, no-answer, canceled)
    to /telephony/status. We skip non-terminal statuses (ringing, in-progress)
    since the call isn't done yet.

    Resolution logic:
      - If `resolution` is explicitly provided, use it (only if not already set).
      - If the agent already set a resolution during the call, preserve it.
      - If not, derive it from the Twilio status: "completed" → "resolved",
        anything else → "abandoned".

    For transferred calls this is called twice: once at the moment of transfer
    (DialCallStatus callback) with resolution="transferred", and again at the
    terminal callback after the bridged leg ends. The second call is a no-op
    for ended_at and duration_sec since they are already set.
    """
    if twilio_status not in _TERMINAL_STATUSES:
        return None

    call = await get_by_sid(db, twilio_call_sid)
    if not call:
        return None

    # Only write timing fields if not already set (preserves transfer-time values
    # when the terminal callback fires after the bridged leg completes).
    if call.ended_at is None:
        call.ended_at = datetime.now(timezone.utc)
    if call.duration_sec is None:
        call.duration_sec = duration_sec

    if call.resolution is None:
        if resolution is not None:
            call.resolution = resolution
        else:
            call.resolution = "resolved" if twilio_status == "completed" else "abandoned"

    await db.flush()
    return call


async def flag_safety_event(db: AsyncSession, caller_phone: str) -> Call | None:
    """Mark the most recent call from caller_phone as a safety event."""
    result = await db.execute(
        select(Call)
        .where(Call.caller_phone == caller_phone)
        .order_by(Call.started_at.desc())
        .limit(1)
    )
    call = result.scalar_one_or_none()
    if call:
        call.safety_event = True
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


@dataclass
class TodayStats:
    calls_today: int
    safety_events_today: int
    avg_duration_today: float | None


async def get_today_stats(db: AsyncSession) -> TodayStats:
    """Return aggregate counts for calls started today (UTC)."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    calls_today = (
        await db.execute(
            select(func.count()).select_from(Call).where(Call.started_at >= today_start)
        )
    ).scalar_one()

    safety_events_today = (
        await db.execute(
            select(func.count())
            .select_from(Call)
            .where(Call.started_at >= today_start, Call.safety_event.is_(True))
        )
    ).scalar_one()

    avg_duration_today = (
        await db.execute(
            select(func.avg(Call.duration_sec))
            .where(Call.started_at >= today_start, Call.duration_sec.isnot(None))
        )
    ).scalar_one()

    return TodayStats(
        calls_today=calls_today,
        safety_events_today=safety_events_today,
        avg_duration_today=float(avg_duration_today) if avg_duration_today is not None else None,
    )


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
