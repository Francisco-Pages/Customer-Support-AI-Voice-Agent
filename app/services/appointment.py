"""
Appointment service — CRUD operations on the appointments table.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment


async def create(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    call_id: uuid.UUID | None = None,
    appointment_type: str,
    scheduled_at: datetime,
    notes: str | None = None,
) -> Appointment:
    appt = Appointment(
        customer_id=customer_id,
        call_id=call_id,
        appointment_type=appointment_type,
        scheduled_at=scheduled_at,
        notes=notes,
    )
    db.add(appt)
    await db.flush()
    return appt


async def get_for_customer(
    db: AsyncSession,
    customer_id: uuid.UUID,
    *,
    limit: int = 5,
) -> list[Appointment]:
    result = await db.execute(
        select(Appointment)
        .where(Appointment.customer_id == customer_id)
        .order_by(Appointment.scheduled_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def update(
    db: AsyncSession,
    appointment_id: uuid.UUID,
    *,
    scheduled_at: datetime | None = None,
    status: str | None = None,
    notes: str | None = None,
) -> Appointment | None:
    result = await db.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )
    appt = result.scalar_one_or_none()
    if not appt:
        return None
    if scheduled_at is not None:
        appt.scheduled_at = scheduled_at
    if status is not None:
        appt.status = status
    if notes is not None:
        appt.notes = notes
    await db.flush()
    return appt
