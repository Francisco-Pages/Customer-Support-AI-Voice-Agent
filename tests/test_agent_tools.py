"""
Unit tests for the @function_tool methods on HVACAssistant (agent/core.py).
DB sessions, Twilio, and geo_service are fully mocked.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from livekit.agents.llm import find_function_tools

from agent.core import HVACAssistant


# ---------------------------------------------------------------------------
# Helpers — plain SimpleNamespace objects avoid SQLAlchemy instrumentation
# ---------------------------------------------------------------------------


def _tool(agent: HVACAssistant, name: str):
    """Return a coroutine factory for the named @function_tool on agent."""
    for t in find_function_tools(type(agent)):
        if t.info.name == name:
            return lambda **kw: t._func(agent, **kw)
    raise ValueError(f"Tool {name!r} not found on {type(agent).__name__}")


def _make_customer(**kw) -> SimpleNamespace:
    c = SimpleNamespace()
    c.id = kw.get("id", uuid4())
    c.phone = kw.get("phone", "+15551234567")
    c.name = kw.get("name", "Jane Smith")
    c.address = kw.get("address", "123 Oak Lane")
    c.tcpa_consent = True
    c.products = kw.get("products", [])
    return c


def _make_product(**kw) -> SimpleNamespace:
    p = SimpleNamespace()
    p.id = uuid4()
    p.product_model = kw.get("product_model", "CoolBreeze 5000")
    p.product_line = kw.get("product_line", "residential")
    p.serial_number = kw.get("serial_number", "SN-TEST-001")
    p.warranty_end_date = kw.get("warranty_end_date", None)
    return p


def _make_appt(**kw) -> SimpleNamespace:
    a = SimpleNamespace()
    a.id = kw.get("id", uuid4())
    a.customer_id = kw.get("customer_id", uuid4())
    a.appointment_type = kw.get("appointment_type", "service")
    a.scheduled_at = kw.get("scheduled_at", datetime(2026, 4, 15, 10, 0))
    a.status = kw.get("status", "scheduled")
    a.notes = kw.get("notes", None)
    return a


def _make_call(**kw) -> SimpleNamespace:
    c = SimpleNamespace()
    c.id = uuid4()
    c.direction = kw.get("direction", "inbound")
    c.started_at = kw.get(
        "started_at", datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
    )
    c.resolution = kw.get("resolution", "resolved")
    c.summary = kw.get("summary", "Customer asked about warranty.")
    return c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def assistant():
    """HVACAssistant with Twilio client mocked out."""
    with patch("agent.core.TwilioClient"):
        return HVACAssistant()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def patched_session(mock_db):
    """Replace AsyncSessionLocal so every tool uses the shared mock_db."""

    @asynccontextmanager
    async def _factory():
        yield mock_db

    with patch("agent.core.AsyncSessionLocal", _factory):
        yield mock_db


# ---------------------------------------------------------------------------
# lookup_customer
# ---------------------------------------------------------------------------


async def test_lookup_customer_not_found(assistant, patched_session):
    with patch("agent.core.customer_service.get_by_phone_with_products", return_value=None):
        result = await _tool(assistant, "lookup_customer")(phone="+15551234567")

    assert "No customer record found" in result


async def test_lookup_customer_found_with_products(assistant, patched_session):
    product = _make_product(
        serial_number="SN-WARRANTY",
        warranty_end_date=datetime(2028, 6, 30, tzinfo=timezone.utc),
    )
    customer = _make_customer(name="Jane Smith", products=[product])

    with patch("agent.core.customer_service.get_by_phone_with_products", return_value=customer):
        result = await _tool(assistant, "lookup_customer")(phone="+15551234567")

    assert "Jane Smith" in result
    assert "SN-WARRANTY" in result
    assert "2028" in result


async def test_lookup_customer_no_products(assistant, patched_session):
    customer = _make_customer(name="Bob Jones", products=[])

    with patch("agent.core.customer_service.get_by_phone_with_products", return_value=customer):
        result = await _tool(assistant, "lookup_customer")(phone="+15551234567")

    assert "Bob Jones" in result
    assert "No registered products" in result


# ---------------------------------------------------------------------------
# lookup_warranty
# ---------------------------------------------------------------------------


async def test_lookup_warranty_serial_not_found(assistant, patched_session, mock_db):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    result = await _tool(assistant, "lookup_warranty")(serial_number="DOESNOTEXIST")

    assert "No product found" in result


async def test_lookup_warranty_active(assistant, patched_session, mock_db):
    product = _make_product(
        product_model="ArcticFlow 3000",
        serial_number="SN-ACTIVE",
        warranty_end_date=datetime(2028, 12, 31, tzinfo=timezone.utc),
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = product
    mock_db.execute.return_value = mock_result

    result = await _tool(assistant, "lookup_warranty")(serial_number="SN-ACTIVE")

    assert "under warranty" in result
    assert "2028" in result


async def test_lookup_warranty_expired(assistant, patched_session, mock_db):
    product = _make_product(
        product_model="OldUnit 1000",
        serial_number="SN-EXPIRED",
        warranty_end_date=datetime(2022, 3, 15, tzinfo=timezone.utc),
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = product
    mock_db.execute.return_value = mock_result

    result = await _tool(assistant, "lookup_warranty")(serial_number="SN-EXPIRED")

    assert "expired" in result.lower()
    assert "2022" in result


async def test_lookup_warranty_no_expiry_on_file(assistant, patched_session, mock_db):
    product = _make_product(warranty_end_date=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = product
    mock_db.execute.return_value = mock_result

    result = await _tool(assistant, "lookup_warranty")(serial_number="SN-NODATE")

    assert "not on file" in result


# ---------------------------------------------------------------------------
# create_appointment
# ---------------------------------------------------------------------------


async def test_create_appointment_invalid_iso_date(assistant, patched_session):
    result = await _tool(assistant, "create_appointment")(
        customer_phone="+15551234567",
        appointment_type="service",
        scheduled_at_iso="tomorrow at 10am",
    )

    assert "Invalid date format" in result


async def test_create_appointment_customer_not_found(assistant, patched_session):
    with patch("agent.core.customer_service.get_by_phone", return_value=None):
        result = await _tool(assistant, "create_appointment")(
            customer_phone="+15559999999",
            appointment_type="service",
            scheduled_at_iso="2026-04-15T10:00:00",
        )

    assert "Could not find" in result


async def test_create_appointment_success(assistant, patched_session):
    customer = _make_customer()
    appt = _make_appt(appointment_type="service", scheduled_at=datetime(2026, 4, 15, 10, 0))

    with patch("agent.core.customer_service.get_by_phone", return_value=customer), \
         patch("agent.core.appointment_service.create", return_value=appt):
        result = await _tool(assistant, "create_appointment")(
            customer_phone="+15551234567",
            appointment_type="service",
            scheduled_at_iso="2026-04-15T10:00:00",
        )

    assert "Appointment created" in result
    assert str(appt.id) in result


# ---------------------------------------------------------------------------
# update_appointment
# ---------------------------------------------------------------------------


async def test_update_appointment_no_changes_specified(assistant, patched_session):
    result = await _tool(assistant, "update_appointment")(
        appointment_id=str(uuid4()),
    )

    assert "No changes" in result


async def test_update_appointment_invalid_uuid(assistant, patched_session):
    result = await _tool(assistant, "update_appointment")(
        appointment_id="this-is-not-a-uuid",
        new_status="confirmed",
    )

    assert "Invalid appointment ID" in result


async def test_update_appointment_not_found(assistant, patched_session):
    with patch("agent.core.appointment_service.update", return_value=None):
        result = await _tool(assistant, "update_appointment")(
            appointment_id=str(uuid4()),
            new_status="confirmed",
        )

    assert "No appointment found" in result


async def test_update_appointment_success(assistant, patched_session):
    appt = _make_appt(status="confirmed")

    with patch("agent.core.appointment_service.update", return_value=appt):
        result = await _tool(assistant, "update_appointment")(
            appointment_id=str(appt.id),
            new_status="confirmed",
        )

    assert str(appt.id) in result
    assert "confirmed" in result


# ---------------------------------------------------------------------------
# get_call_history
# ---------------------------------------------------------------------------


async def test_get_call_history_customer_not_found(assistant, patched_session):
    with patch("agent.core.customer_service.get_by_phone", return_value=None):
        result = await _tool(assistant, "get_call_history")(customer_phone="+15559999999")

    assert "No customer record found" in result


async def test_get_call_history_no_calls(assistant, patched_session):
    customer = _make_customer()

    with patch("agent.core.customer_service.get_by_phone", return_value=customer), \
         patch("agent.core.call_service.list_calls", return_value=(0, [])):
        result = await _tool(assistant, "get_call_history")(customer_phone="+15551234567")

    assert "No previous call history" in result


async def test_get_call_history_returns_summaries(assistant, patched_session):
    customer = _make_customer()
    calls = [
        _make_call(summary="Asked about warranty on model 5000.", resolution="resolved"),
        _make_call(summary="Scheduled a maintenance visit.", resolution="resolved"),
    ]

    with patch("agent.core.customer_service.get_by_phone", return_value=customer), \
         patch("agent.core.call_service.list_calls", return_value=(2, calls)):
        result = await _tool(assistant, "get_call_history")(customer_phone="+15551234567")

    assert "warranty" in result.lower()
    assert "maintenance" in result.lower()


# ---------------------------------------------------------------------------
# schedule_callback
# ---------------------------------------------------------------------------


async def test_schedule_callback_invalid_time(assistant, patched_session):
    result = await _tool(assistant, "schedule_callback")(
        customer_phone="+15551234567",
        preferred_time_iso="next Tuesday",
        reason="billing question",
    )

    assert "Invalid time format" in result


async def test_schedule_callback_success(assistant, patched_session):
    customer = _make_customer()
    appt = _make_appt(appointment_type="callback")

    with patch("agent.core.customer_service.get_by_phone", return_value=customer), \
         patch("agent.core.appointment_service.create", return_value=appt):
        result = await _tool(assistant, "schedule_callback")(
            customer_phone="+15551234567",
            preferred_time_iso="2026-04-20T14:00:00",
            reason="billing dispute",
        )

    assert "Callback scheduled" in result
    assert str(appt.id) in result


# ---------------------------------------------------------------------------
# send_appointment_sms
# ---------------------------------------------------------------------------


async def test_send_sms_success(assistant):
    # _twilio is a MagicMock (patched in the fixture), so messages.create succeeds by default
    result = await _tool(assistant, "send_appointment_sms")(
        customer_phone="+15551234567",
        message="Your service appointment is on April 15 at 10 AM.",
    )

    assert "SMS confirmation sent" in result


async def test_send_sms_twilio_failure(assistant):
    assistant._twilio.messages.create.side_effect = Exception("Twilio API error")

    result = await _tool(assistant, "send_appointment_sms")(
        customer_phone="+15551234567",
        message="Your service appointment is on April 15 at 10 AM.",
    )

    assert "could not be sent" in result.lower()
    assert "still saved" in result


# ---------------------------------------------------------------------------
# search_technicians
# ---------------------------------------------------------------------------


async def test_search_technicians_no_results(assistant):
    with patch("agent.core.geo_service.search", return_value=[]):
        result = await _tool(assistant, "search_technicians")(city="Austin", state="TX")

    assert "No certified technicians" in result


async def test_search_technicians_returns_list(assistant):
    records = [
        {"name": "CoolAir Services", "city": "Austin", "state": "TX",
         "phone": "+15125550001", "address": ""},
        {"name": "Frost HVAC", "city": "Round Rock", "state": "TX",
         "phone": "+15125550002", "address": ""},
    ]
    with patch("agent.core.geo_service.search", return_value=records):
        result = await _tool(assistant, "search_technicians")(city="Austin", state="TX")

    assert "CoolAir Services" in result
    assert "Frost HVAC" in result
    assert "+15125550001" in result


async def test_search_technicians_passes_correct_record_type(assistant):
    with patch("agent.core.geo_service.search", return_value=[]) as mock_search:
        await _tool(assistant, "search_technicians")(city="Austin", state="TX")

    mock_search.assert_called_once_with("Austin", "TX", record_type="technician")


# ---------------------------------------------------------------------------
# search_distributors
# ---------------------------------------------------------------------------


async def test_search_distributors_no_results(assistant):
    with patch("agent.core.geo_service.search", return_value=[]):
        result = await _tool(assistant, "search_distributors")(city="Dallas", state="TX")

    assert "No authorized distributors" in result


async def test_search_distributors_returns_list(assistant):
    records = [
        {"name": "Parts Depot", "city": "Dallas", "state": "TX",
         "phone": "+12145550001", "address": ""},
    ]
    with patch("agent.core.geo_service.search", return_value=records):
        result = await _tool(assistant, "search_distributors")(city="Dallas", state="TX")

    assert "Parts Depot" in result
    assert "+12145550001" in result


async def test_search_distributors_passes_correct_record_type(assistant):
    with patch("agent.core.geo_service.search", return_value=[]) as mock_search:
        await _tool(assistant, "search_distributors")(city="Houston", state="TX")

    mock_search.assert_called_once_with("Houston", "TX", record_type="distributor")
