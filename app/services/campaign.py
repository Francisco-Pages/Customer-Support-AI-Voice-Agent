"""
Campaign service — enqueue outbound calls and query the outbound_queue.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Customer, OutboundQueue


async def enqueue(
    db: AsyncSession,
    customer_ids: list[uuid.UUID],
    campaign_type: str,
    scheduled_at: datetime,
) -> tuple[int, int]:
    """
    Enqueue outbound calls for a list of customers.

    Validates TCPA consent for each customer before inserting into
    outbound_queue. Customers without consent (or not found) are skipped.

    Returns (queued, blocked_no_consent).
    """
    queued = 0
    blocked = 0

    for cid in customer_ids:
        result = await db.execute(select(Customer).where(Customer.id == cid))
        customer = result.scalar_one_or_none()

        if customer is None or not customer.tcpa_consent:
            blocked += 1
            continue

        db.add(
            OutboundQueue(
                customer_id=cid,
                campaign_type=campaign_type,
                scheduled_at=scheduled_at,
            )
        )
        queued += 1

    if queued:
        await db.flush()

    return queued, blocked


async def list_queue(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[OutboundQueue]]:
    """Return (total_count, page) ordered by scheduled_at ascending."""
    count_q = select(func.count()).select_from(OutboundQueue)
    data_q = select(OutboundQueue).order_by(OutboundQueue.scheduled_at.asc())

    if status is not None:
        count_q = count_q.where(OutboundQueue.status == status)
        data_q = data_q.where(OutboundQueue.status == status)

    total = (await db.execute(count_q)).scalar_one()
    rows = (await db.execute(data_q.limit(limit).offset(offset))).scalars().all()

    return total, list(rows)
