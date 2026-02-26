"""
Admin REST API.

All endpoints require the X-Api-Key header matching ADMIN_API_KEY in settings.
No customer-facing or Twilio-facing logic lives here — this is purely for
internal operations: launching outbound campaigns, querying call records,
and managing the outbound queue.
"""

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_admin_api_key
from app.dependencies import get_db
from app.services import call as call_service
from app.services import campaign as campaign_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(verify_admin_api_key)],
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CampaignRequest(BaseModel):
    customer_ids: list[UUID] = Field(..., min_length=1)
    campaign_type: str = Field(..., pattern="^(reminder|followup|warranty_alert)$")
    scheduled_at: str = Field(..., description="ISO 8601 datetime")


class CampaignResponse(BaseModel):
    queued: int
    blocked_no_consent: int
    campaign_type: str


class CallRecord(BaseModel):
    id: UUID
    customer_id: UUID | None
    direction: str
    twilio_call_sid: str
    started_at: str | None
    ended_at: str | None
    duration_sec: int | None
    resolution: str | None
    summary: str | None
    safety_event: bool


class CallListResponse(BaseModel):
    total: int
    calls: list[CallRecord]


class QueueEntry(BaseModel):
    id: UUID
    customer_id: UUID
    campaign_type: str
    scheduled_at: str
    status: str
    attempts: int
    twilio_call_sid: str | None


class QueueListResponse(BaseModel):
    total: int
    entries: list[QueueEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid ISO 8601 datetime for '{field}': {value!r}",
        )


def _call_to_record(call) -> CallRecord:
    return CallRecord(
        id=call.id,
        customer_id=call.customer_id,
        direction=call.direction,
        twilio_call_sid=call.twilio_call_sid,
        started_at=call.started_at.isoformat() if call.started_at else None,
        ended_at=call.ended_at.isoformat() if call.ended_at else None,
        duration_sec=call.duration_sec,
        resolution=call.resolution,
        summary=call.summary,
        safety_event=call.safety_event,
    )


def _queue_to_entry(entry) -> QueueEntry:
    return QueueEntry(
        id=entry.id,
        customer_id=entry.customer_id,
        campaign_type=entry.campaign_type,
        scheduled_at=entry.scheduled_at.isoformat(),
        status=entry.status,
        attempts=entry.attempts,
        twilio_call_sid=entry.twilio_call_sid,
    )


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Enqueue an outbound call campaign for a list of customers.

    Validates TCPA consent per customer before inserting into outbound_queue.
    Returns a count of queued vs. blocked (no consent) entries.
    """
    scheduled_at = _parse_dt(payload.scheduled_at, "scheduled_at")

    logger.info(
        "Campaign enqueue | type=%s customers=%d scheduled_at=%s",
        payload.campaign_type,
        len(payload.customer_ids),
        scheduled_at,
    )

    queued, blocked = await campaign_service.enqueue(
        db,
        customer_ids=payload.customer_ids,
        campaign_type=payload.campaign_type,
        scheduled_at=scheduled_at,
    )

    return CampaignResponse(
        queued=queued,
        blocked_no_consent=blocked,
        campaign_type=payload.campaign_type,
    )


# ---------------------------------------------------------------------------
# Call records
# ---------------------------------------------------------------------------


@router.get("/calls", response_model=CallListResponse)
async def list_calls(
    customer_id: Annotated[UUID | None, Query(description="Filter by customer UUID")] = None,
    resolution: Annotated[str | None, Query(description="Filter by resolution status")] = None,
    safety_event: Annotated[bool | None, Query(description="Safety-flagged calls only")] = None,
    date_from: Annotated[str | None, Query(description="ISO 8601 start date")] = None,
    date_to: Annotated[str | None, Query(description="ISO 8601 end date")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
):
    """Paginated call records with optional filters, ordered by start time descending."""
    total, calls = await call_service.list_calls(
        db,
        customer_id=customer_id,
        resolution=resolution,
        safety_event=safety_event,
        date_from=_parse_dt(date_from, "date_from"),
        date_to=_parse_dt(date_to, "date_to"),
        limit=limit,
        offset=offset,
    )
    return CallListResponse(total=total, calls=[_call_to_record(c) for c in calls])


@router.get("/calls/{call_id}", response_model=CallRecord)
async def get_call(call_id: UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve a single call record by UUID."""
    call = await call_service.get_by_id(db, call_id)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found.")
    return _call_to_record(call)


# ---------------------------------------------------------------------------
# Outbound queue
# ---------------------------------------------------------------------------


@router.get("/queue", response_model=QueueListResponse)
async def list_queue(
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
):
    """List outbound queue entries with optional status filter."""
    total, entries = await campaign_service.list_queue(
        db, status=status_filter, limit=limit, offset=offset
    )
    return QueueListResponse(
        total=total, entries=[_queue_to_entry(e) for e in entries]
    )
