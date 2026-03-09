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

from geopy.geocoders import Nominatim
from geopy.adapters import AioHTTPAdapter
from pinecone import Pinecone

from app.config import settings

logger = logging.getLogger(__name__)


async def geocode_city_state(city: str, state: str) -> tuple[float, float] | None:
    """
    Resolve a US city + state to (latitude, longitude) using geopy's async
    Nominatim adapter. Free, no API key required.

    Returns None on network error or if the location is not found.
    """
    try:
        async with Nominatim(
            user_agent="HVACVoiceAgent/1.0", adapter_factory=AioHTTPAdapter
        ) as geolocator:
            location = await geolocator.geocode(f"{city}, {state}, USA")
    except Exception:
        logger.warning(
            "Geocoding failed for %r, %r", city, state, exc_info=True
        )
        return None

    if not location:
        logger.info("No geocoding result for %r, %r", city, state)
        return None

    return location.latitude, location.longitude


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
    # Vectors are stored in named namespaces ("technicians" / "distributors").
    # Metadata field names differ per record type:
    #   technicians:  technician_name, phone_number, address
    #   distributors: distributor_name, phone_number, address
    # The address field contains "Street, City, State" — city and state are
    # parsed from the last two comma-separated parts.
    namespace = "technicians" if record_type == "technician" else "distributors"
    name_field = "technician_name" if record_type == "technician" else "distributor_name"
    index = _geo_index()
    results = index.query(
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )
    records = []
    for m in results.matches:
        meta = m.metadata
        address = meta.get("address", "")
        parts = [p.strip() for p in address.split(",")]
        city = parts[-2] if len(parts) >= 2 else ""
        state = parts[-1] if len(parts) >= 1 else ""
        record = {
            "name": meta.get(name_field, "Unknown"),
            "city": city,
            "state": state,
            "phone": meta.get("phone_number", "N/A"),
            "address": address,
        }
        website = meta.get("website", "")
        if website:
            record["website"] = website
        records.append(record)
    return records


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
