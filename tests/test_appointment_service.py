"""
Unit tests for app/services/appointment.py.
All DB interactions are mocked — no live database required.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.appointment import create, get_for_customer, update


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_appt(**kw) -> SimpleNamespace:
    """Lightweight stand-in for an Appointment ORM row (no SQLAlchemy state needed)."""
    a = SimpleNamespace()
    a.id = kw.get("id", uuid4())
    a.customer_id = kw.get("customer_id", uuid4())
    a.call_id = kw.get("call_id", None)
    a.appointment_type = kw.get("appointment_type", "service")
    a.scheduled_at = kw.get(
        "scheduled_at", datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    )
    a.status = kw.get("status", "scheduled")
    a.notes = kw.get("notes", None)
    return a


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_returns_appointment_with_correct_fields():
    from app.db.models import Appointment

    db = _mock_db()
    customer_id = uuid4()
    scheduled_at = datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc)

    appt = await create(
        db,
        customer_id=customer_id,
        appointment_type="maintenance",
        scheduled_at=scheduled_at,
    )

    assert isinstance(appt, Appointment)
    assert appt.customer_id == customer_id
    assert appt.appointment_type == "maintenance"
    assert appt.scheduled_at == scheduled_at
    assert appt.notes is None


async def test_create_with_optional_fields():
    call_id = uuid4()

    db = _mock_db()
    appt = await create(
        db,
        customer_id=uuid4(),
        call_id=call_id,
        appointment_type="inspection",
        scheduled_at=datetime(2026, 5, 1, 14, 0),
        notes="Unit making rattling noise",
    )

    assert appt.call_id == call_id
    assert appt.notes == "Unit making rattling noise"
    assert appt.appointment_type == "inspection"


async def test_create_calls_db_add_and_flush():
    db = _mock_db()

    appt = await create(
        db,
        customer_id=uuid4(),
        appointment_type="service",
        scheduled_at=datetime(2026, 4, 1, 10, 0),
    )

    db.add.assert_called_once_with(appt)
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_for_customer
# ---------------------------------------------------------------------------


async def test_get_for_customer_returns_list():
    db = _mock_db()
    customer_id = uuid4()
    expected = [_make_appt(customer_id=customer_id) for _ in range(3)]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = expected
    db.execute.return_value = mock_result

    result = await get_for_customer(db, customer_id)

    db.execute.assert_awaited_once()
    assert result == expected


async def test_get_for_customer_empty_returns_empty_list():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    result = await get_for_customer(db, uuid4())

    assert result == []


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


async def test_update_scheduled_at():
    db = _mock_db()
    appt = _make_appt()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = appt
    db.execute.return_value = mock_result

    new_dt = datetime(2026, 6, 1, 11, 0)
    result = await update(db, appt.id, scheduled_at=new_dt)

    assert result is appt
    assert appt.scheduled_at == new_dt
    db.flush.assert_awaited_once()


async def test_update_status():
    db = _mock_db()
    appt = _make_appt()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = appt
    db.execute.return_value = mock_result

    await update(db, appt.id, status="confirmed")

    assert appt.status == "confirmed"


async def test_update_notes():
    db = _mock_db()
    appt = _make_appt()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = appt
    db.execute.return_value = mock_result

    await update(db, appt.id, notes="Check refrigerant level")

    assert appt.notes == "Check refrigerant level"


async def test_update_not_found_returns_none():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    result = await update(db, uuid4(), status="confirmed")

    assert result is None
    db.flush.assert_not_awaited()


async def test_update_skips_none_fields():
    """Fields not passed should not overwrite existing values."""
    db = _mock_db()
    appt = _make_appt(status="scheduled", notes="original note")
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = appt
    db.execute.return_value = mock_result

    # Only update status — notes should remain unchanged
    await update(db, appt.id, status="confirmed")

    assert appt.status == "confirmed"
    assert appt.notes == "original note"
