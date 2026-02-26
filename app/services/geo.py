"""
Geo service — geocode a US city/state to a unit-sphere vector and query the
Pinecone geo-directory index to find nearby technicians or distributors.

Index layout (hvac-geo-directory):
  Dimensions : 3
  Metric     : dotproduct
  Each vector: [X, Y, Z] = cos/sin projection of (lat, lon) onto the unit sphere.
      X = cos(φ) · cos(λ)
      Y = cos(φ) · sin(λ)
      Z = sin(φ)
  A dot-product query maximises for the nearest point on the sphere, equivalent
  to minimising great-circle distance.
"""

import asyncio
import logging
import math
from functools import lru_cache

import httpx
from pinecone import Pinecone

from app.config import settings

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy requires a descriptive User-Agent.
_USER_AGENT = "HVACVoiceAgent/1.0 (voice customer support; contact: ops@example.com)"


async def geocode_city_state(city: str, state: str) -> tuple[float, float] | None:
    """
    Resolve a US city + state to (latitude, longitude) using the Nominatim API.
    Returns None on network error or if the location is not found.
    """
    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        try:
            resp = await client.get(
                _NOMINATIM_URL,
                params={
                    "city": city,
                    "state": state,
                    "country": "US",
                    "format": "json",
                    "limit": 1,
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning(
                "Nominatim geocoding failed for %r, %r", city, state, exc_info=True
            )
            return None

    if not data:
        logger.info("No geocoding result for %r, %r", city, state)
        return None

    return float(data[0]["lat"]), float(data[0]["lon"])


def _latlon_to_xyz(lat: float, lon: float) -> list[float]:
    phi = math.radians(lat)
    lam = math.radians(lon)
    return [
        math.cos(phi) * math.cos(lam),
        math.cos(phi) * math.sin(lam),
        math.sin(phi),
    ]


@lru_cache(maxsize=1)
def _geo_index():
    """Lazy singleton Pinecone index for the geo-directory (synchronous SDK)."""
    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_geo_index_name)


def _sync_query(vector: list[float], record_type: str, top_k: int) -> list[dict]:
    """Run synchronously inside a thread executor."""
    index = _geo_index()
    results = index.query(
        vector=vector,
        top_k=top_k,
        filter={"record_type": {"$eq": record_type}},
        include_metadata=True,
    )
    return [
        {
            "name": m.metadata.get("name", "Unknown"),
            "city": m.metadata.get("city", ""),
            "state": m.metadata.get("state", ""),
            "phone": m.metadata.get("phone", "N/A"),
            "address": m.metadata.get("address", ""),
        }
        for m in results.matches
    ]


async def search(
    city: str,
    state: str,
    record_type: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Return the nearest technicians or distributors for a given US city and state.

    Args:
        city: City name (e.g. "Austin").
        state: State name or two-letter code (e.g. "TX" or "Texas").
        record_type: "technician" | "distributor"
        top_k: Maximum number of results to return (default 5).

    Returns:
        List of dicts with keys: name, city, state, phone, address.
        Empty list if geocoding fails or no records are found.
    """
    coords = await geocode_city_state(city, state)
    if coords is None:
        return []

    vector = _latlon_to_xyz(*coords)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _sync_query, vector, record_type, top_k
    )
