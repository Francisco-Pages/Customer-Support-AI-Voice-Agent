"""
Unit tests for app/services/geo.py.
Nominatim HTTP calls and Pinecone queries are fully mocked.
"""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.geo import _latlon_to_xyz, geocode_city_state, search


# ---------------------------------------------------------------------------
# _latlon_to_xyz — pure math, no mocks needed
# ---------------------------------------------------------------------------


def test_latlon_to_xyz_produces_unit_vector():
    """The Cartesian projection of any lat/lon must land on the unit sphere."""
    test_cases = [
        (0.0, 0.0),           # equator / prime meridian
        (30.267, -97.743),    # Austin, TX
        (40.713, -74.006),    # New York, NY
        (34.052, -118.244),   # Los Angeles, CA
        (90.0, 0.0),          # north pole
        (-90.0, 0.0),         # south pole
    ]
    for lat, lon in test_cases:
        x, y, z = _latlon_to_xyz(lat, lon)
        magnitude = math.sqrt(x**2 + y**2 + z**2)
        assert abs(magnitude - 1.0) < 1e-10, (
            f"Not a unit vector for lat={lat} lon={lon}: magnitude={magnitude}"
        )


def test_latlon_to_xyz_north_pole():
    """North pole (lat=90) should map to [0, 0, 1]."""
    x, y, z = _latlon_to_xyz(90.0, 0.0)
    assert abs(x) < 1e-10
    assert abs(y) < 1e-10
    assert abs(z - 1.0) < 1e-10


def test_latlon_to_xyz_south_pole():
    """South pole (lat=-90) should map to [0, 0, -1]."""
    x, y, z = _latlon_to_xyz(-90.0, 0.0)
    assert abs(x) < 1e-10
    assert abs(y) < 1e-10
    assert abs(z + 1.0) < 1e-10


def test_latlon_to_xyz_equator_prime_meridian():
    """Equator at prime meridian (0, 0) should map to [1, 0, 0]."""
    x, y, z = _latlon_to_xyz(0.0, 0.0)
    assert abs(x - 1.0) < 1e-10
    assert abs(y) < 1e-10
    assert abs(z) < 1e-10


def test_latlon_to_xyz_three_values():
    """Result must always be a list of exactly 3 floats."""
    result = _latlon_to_xyz(30.0, -90.0)
    assert len(result) == 3
    assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# geocode_city_state — mocks httpx
# ---------------------------------------------------------------------------


def _mock_nominatim_client(lat: str, lon: str) -> tuple:
    """Return (mock_class, mock_client) set up for a successful Nominatim response."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{"lat": lat, "lon": lon}]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    return mock_cls, mock_client


async def test_geocode_returns_lat_lon_for_known_city():
    mock_cls, _ = _mock_nominatim_client("30.267153", "-97.7430608")

    with patch("app.services.geo.httpx.AsyncClient", mock_cls):
        result = await geocode_city_state("Austin", "TX")

    assert result == pytest.approx((30.267153, -97.7430608))


async def test_geocode_empty_response_returns_none():
    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.geo.httpx.AsyncClient", mock_cls):
        result = await geocode_city_state("Notacityname", "ZZ")

    assert result is None


async def test_geocode_network_error_returns_none():
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection refused")
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.geo.httpx.AsyncClient", mock_cls):
        result = await geocode_city_state("Austin", "TX")

    assert result is None


async def test_geocode_http_error_returns_none():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("404 Not Found")
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.geo.httpx.AsyncClient", mock_cls):
        result = await geocode_city_state("Austin", "TX")

    assert result is None


# ---------------------------------------------------------------------------
# search — end-to-end mock (geocode + Pinecone)
# ---------------------------------------------------------------------------


async def test_search_returns_matched_records():
    fake_records = [
        {
            "name": "ArcticAir Services",
            "city": "Austin",
            "state": "TX",
            "phone": "+15125550001",
            "address": "100 Cool St",
        },
        {
            "name": "FrostWorks HVAC",
            "city": "Round Rock",
            "state": "TX",
            "phone": "+15125550002",
            "address": "200 Ice Ave",
        },
    ]
    with patch("app.services.geo.geocode_city_state", return_value=(30.267, -97.743)), \
         patch("app.services.geo._sync_query", return_value=fake_records):
        results = await search("Austin", "TX", "technician")

    assert results == fake_records


async def test_search_passes_record_type_to_pinecone():
    """_sync_query must receive the correct record_type."""
    with patch("app.services.geo.geocode_city_state", return_value=(30.267, -97.743)) as _gc, \
         patch("app.services.geo._sync_query", return_value=[]) as mock_query:
        await search("Austin", "TX", "distributor", top_k=3)

    # _sync_query is called via run_in_executor; extract call args
    call_args = mock_query.call_args
    assert call_args.args[1] == "distributor"
    assert call_args.args[2] == 3


async def test_search_returns_empty_when_geocoding_fails():
    with patch("app.services.geo.geocode_city_state", return_value=None):
        results = await search("???", "??", "technician")

    assert results == []


async def test_search_passes_xyz_vector_to_pinecone():
    """The vector passed to Pinecone must be the XYZ projection of the geocoded coords."""
    lat, lon = 30.267, -97.743
    expected_xyz = _latlon_to_xyz(lat, lon)

    with patch("app.services.geo.geocode_city_state", return_value=(lat, lon)), \
         patch("app.services.geo._sync_query", return_value=[]) as mock_query:
        await search("Austin", "TX", "technician")

    actual_vector = mock_query.call_args.args[0]
    assert actual_vector == pytest.approx(expected_xyz, abs=1e-9)
