"""
Admin REST API.

All endpoints require the X-Api-Key header matching ADMIN_API_KEY in settings.
No customer-facing or Twilio-facing logic lives here — this is purely for
internal operations: launching outbound campaigns, querying call records,
and managing the outbound queue.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.security import verify_admin_api_key

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
    customer_ids: list[UUID] = Field(..., min_length=1, description="List of customer UUIDs to target")
    campaign_type: str = Field(..., pattern="^(reminder|followup|warranty_alert)$")
    scheduled_at: str = Field(..., description="ISO 8601 datetime for when to dispatch calls")


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


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: CampaignRequest):
    """
    Enqueue an outbound call campaign for a list of customers.

    - Validates TCPA consent for each customer before inserting into outbound_queue.
    - Customers without consent are counted in blocked_no_consent and skipped.
    - Returns a summary of how many calls were queued vs. blocked.

    TODO: Implement DB insert into outbound_queue after consent check.
    """
    logger.info(
        "Campaign enqueue request | type=%s customers=%d scheduled_at=%s",
        payload.campaign_type,
        len(payload.customer_ids),
        payload.scheduled_at,
    )

    # TODO: For each customer_id:
    #   1. Fetch customer record from PostgreSQL
    #   2. If tcpa_consent is False: increment blocked count, skip
    #   3. If tcpa_consent is True: insert into outbound_queue
    # queued, blocked = await campaign_service.enqueue(payload)

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Campaign service not yet implemented.",
    )


# ---------------------------------------------------------------------------
# Call records
# ---------------------------------------------------------------------------

@router.get("/calls", response_model=CallListResponse)
async def list_calls(
    customer_id: Annotated[UUID | None, Query(description="Filter by customer UUID")] = None,
    resolution: Annotated[str | None, Query(description="Filter by resolution status")] = None,
    safety_event: Annotated[bool | None, Query(description="Filter to safety-flagged calls only")] = None,
    date_from: Annotated[str | None, Query(description="ISO 8601 start date filter")] = None,
    date_to: Annotated[str | None, Query(description="ISO 8601 end date filter")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Query call records with optional filters.

    Supports filtering by: customer ID, resolution status, safety event flag,
    and date range. Returns paginated results ordered by started_at descending.

    TODO: Implement query against calls table in PostgreSQL.
    """
    logger.info(
        "Call record query | customer_id=%s resolution=%s safety=%s",
        customer_id,
        resolution,
        safety_event,
    )

    # TODO: Build and execute SQLAlchemy query with applied filters
    # calls = await call_service.list_calls(
    #     customer_id=customer_id,
    #     resolution=resolution,
    #     safety_event=safety_event,
    #     date_from=date_from,
    #     date_to=date_to,
    #     limit=limit,
    #     offset=offset,
    # )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Call record service not yet implemented.",
    )


@router.get("/calls/{call_id}", response_model=CallRecord)
async def get_call(call_id: UUID):
    """
    Retrieve a single call record by UUID, including full transcript and summary.

    TODO: Implement single call lookup from PostgreSQL.
    """
    logger.info("Call detail request | call_id=%s", call_id)

    # TODO: await call_service.get_by_id(call_id)

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Call record service not yet implemented.",
    )


# ---------------------------------------------------------------------------
# Outbound queue management
# ---------------------------------------------------------------------------

@router.get("/queue")
async def list_queue(
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    List records in the outbound_queue.

    Useful for monitoring campaign dispatch progress and identifying blocked records.

    TODO: Implement query against outbound_queue table.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Queue service not yet implemented.",
    )
