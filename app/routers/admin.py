"""
Admin REST API.

All endpoints require the X-Api-Key header matching ADMIN_API_KEY in settings.
No customer-facing or Twilio-facing logic lives here — this is purely for
internal operations: launching outbound campaigns, querying call records,
and managing the outbound queue.
"""

import asyncio
import logging
import math
import uuid
from datetime import datetime
from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from geopy.adapters import AioHTTPAdapter
from geopy.geocoders import Nominatim
from openai import AsyncOpenAI
from pinecone import Pinecone
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import verify_admin_api_key
from app.dependencies import get_db, get_redis
from app.rag.ingestor import delete_document, ingest_document
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
    caller_phone: str | None
    twilio_call_sid: str
    started_at: str | None
    ended_at: str | None
    duration_sec: int | None
    resolution: str | None
    summary: str | None
    transcript: str | None
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


class StatsResponse(BaseModel):
    active_calls: int
    calls_today: int
    safety_events_today: int
    avg_duration_today: float | None
    recent_calls: list[CallRecord]


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
        caller_phone=call.caller_phone,
        twilio_call_sid=call.twilio_call_sid,
        started_at=call.started_at.isoformat() if call.started_at else None,
        ended_at=call.ended_at.isoformat() if call.ended_at else None,
        duration_sec=call.duration_sec,
        resolution=call.resolution,
        summary=call.summary,
        transcript=call.transcript,
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
# Stats
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Live overview: active call count, today's aggregate stats, and 10 most recent calls."""
    active_keys = await redis.keys("active_call:*")
    today = await call_service.get_today_stats(db)
    _, recent = await call_service.list_calls(db, limit=10, offset=0)
    return StatsResponse(
        active_calls=len(active_keys),
        calls_today=today.calls_today,
        safety_events_today=today.safety_events_today,
        avg_duration_today=today.avg_duration_today,
        recent_calls=[_call_to_record(c) for c in recent],
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


# ---------------------------------------------------------------------------
# Knowledge base document ingestion
# ---------------------------------------------------------------------------

_VALID_NAMESPACES = {
    "unit-specs",
    "warranty-policy-details",
    "error-codes",
    "common-troubleshooting",
}


class IngestResponse(BaseModel):
    doc_id: str
    filename: str
    namespace: str
    chunks_ingested: int
    characters_total: int


class DeleteDocumentResponse(BaseModel):
    doc_id: str
    namespace: str
    vectors_deleted: int


@router.post("/documents/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_document_endpoint(
    file: UploadFile,
    namespace: Annotated[
        str,
        Query(description="Target Pinecone namespace: unit-specs | warranty-policy-details | error-codes | common-troubleshooting"),
    ],
):
    """
    Upload a document (.txt .md .pdf .docx), chunk it, embed it, and upsert
    it into the specified Pinecone namespace.

    Re-uploading the same filename overwrites its existing vectors (upsert
    semantics keyed on sha256(filename)).
    """
    if namespace not in _VALID_NAMESPACES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid namespace '{namespace}'. Valid values: {sorted(_VALID_NAMESPACES)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    filename = file.filename or "upload"

    try:
        result = await ingest_document(content=content, filename=filename, namespace=namespace)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    logger.info(
        "Document ingested via API | doc_id=%s file=%s ns=%s chunks=%d",
        result.doc_id,
        filename,
        namespace,
        result.chunks_ingested,
    )
    return IngestResponse(
        doc_id=result.doc_id,
        filename=result.filename,
        namespace=result.namespace,
        chunks_ingested=result.chunks_ingested,
        characters_total=result.characters_total,
    )


@router.delete("/documents/{doc_id}", response_model=DeleteDocumentResponse)
async def delete_document_endpoint(
    doc_id: str,
    namespace: Annotated[
        str,
        Query(description="Pinecone namespace to delete from"),
    ],
):
    """
    Delete all vectors for a document from a Pinecone namespace.

    doc_id is the 12-character identifier returned by the ingest endpoint.
    """
    if namespace not in _VALID_NAMESPACES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid namespace '{namespace}'. Valid values: {sorted(_VALID_NAMESPACES)}",
        )

    deleted = await delete_document(doc_id=doc_id, namespace=namespace)
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No vectors found for doc_id='{doc_id}' in namespace='{namespace}'.",
        )

    return DeleteDocumentResponse(doc_id=doc_id, namespace=namespace, vectors_deleted=deleted)


# ---------------------------------------------------------------------------
# Knowledge base browser
# ---------------------------------------------------------------------------


class NamespaceInfo(BaseModel):
    name: str
    vector_count: int


class NamespacesResponse(BaseModel):
    namespaces: list[NamespaceInfo]


class KnowledgeRecord(BaseModel):
    id: str
    content: str
    metadata: dict


class KnowledgeRecordsResponse(BaseModel):
    namespace: str
    total: int
    records: list[KnowledgeRecord]


def _get_pinecone_index():
    # settings already imported
    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_index_name)


@router.get("/knowledge/namespaces", response_model=NamespacesResponse)
async def list_knowledge_namespaces():
    """Return all Pinecone namespaces with their vector counts."""
    loop = asyncio.get_event_loop()
    index = _get_pinecone_index()
    stats = await loop.run_in_executor(None, index.describe_index_stats)
    namespaces = [
        NamespaceInfo(name=ns, vector_count=data.vector_count)
        for ns, data in sorted(stats.namespaces.items())
    ]
    return NamespacesResponse(namespaces=namespaces)


@router.get("/knowledge/records", response_model=KnowledgeRecordsResponse)
async def list_knowledge_records(
    namespace: Annotated[str, Query(description="Pinecone namespace to browse")],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    search: Annotated[str | None, Query(description="Semantic search query")] = None,
):
    """
    Browse or search records in a Pinecone namespace.

    Without `search`, returns up to `limit` records using a zero vector (arbitrary order).
    With `search`, embeds the query and returns the top `limit` semantically matching records.
    """
    if namespace not in _VALID_NAMESPACES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid namespace '{namespace}'. Valid values: {sorted(_VALID_NAMESPACES)}",
        )

    loop = asyncio.get_event_loop()
    index = _get_pinecone_index()

    def _stats():
        return index.describe_index_stats()

    stats = await loop.run_in_executor(None, _stats)
    total = stats.namespaces[namespace].vector_count if namespace in stats.namespaces else 0

    if search:
        # Semantic search: embed the query then query Pinecone
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.embeddings.create(
            input=search,
            model="text-embedding-3-small",
            dimensions=1536,
        )
        query_vector = response.data[0].embedding

        def _query():
            return index.query(
                vector=query_vector,
                top_k=limit,
                namespace=namespace,
                include_metadata=True,
            )

        results = await loop.run_in_executor(None, _query)
        matches = results.matches
    else:
        # Browse: list IDs then fetch metadata (zero-vector cosine is undefined)
        def _list_and_fetch():
            ids = []
            for id_batch in index.list(namespace=namespace):
                ids.extend(id_batch)
                if len(ids) >= limit:
                    break
            ids = ids[:limit]
            if not ids:
                return []
            fetched = index.fetch(ids=ids, namespace=namespace)
            return list(fetched.vectors.values())

        matches = await loop.run_in_executor(None, _list_and_fetch)

    records = [
        KnowledgeRecord(
            id=m.id,
            content=m.metadata.get("content", ""),
            metadata={k: v for k, v in m.metadata.items() if k != "content"},
        )
        for m in matches
    ]

    return KnowledgeRecordsResponse(namespace=namespace, total=total, records=records)


# ---------------------------------------------------------------------------
# Service directory (geo index — technicians & distributors)
# ---------------------------------------------------------------------------


def _xyz_to_latlon(x: float, y: float, z: float) -> tuple[float, float]:
    """Reverse the unit-sphere projection back to (latitude, longitude) in degrees."""
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z))))
    lon = math.degrees(math.atan2(y, x))
    return round(lat, 6), round(lon, 6)


class LocationRecord(BaseModel):
    id: str
    record_type: str
    name: str
    phone: str
    address: str
    lat: float | None = None
    lon: float | None = None


class LocationsListResponse(BaseModel):
    record_type: str
    total: int
    records: list[LocationRecord]


class AddLocationRequest(BaseModel):
    record_type: str = Field(..., pattern="^(technician|distributor)$")
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    address: str = Field(..., min_length=1, description="Full address e.g. '123 Main St, Austin, TX'")


class AddLocationResponse(BaseModel):
    id: str
    record_type: str
    name: str
    phone: str
    address: str
    lat: float | None = None
    lon: float | None = None


class UpdateLocationRequest(BaseModel):
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    address: str = Field(..., min_length=1, description="Full address e.g. '123 Main St, Austin, TX'")


class DeleteLocationResponse(BaseModel):
    id: str
    record_type: str


def _get_geo_index():
    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_geo_index_name)


@router.get("/locations", response_model=LocationsListResponse)
async def list_locations(
    record_type: Annotated[str, Query(pattern="^(technician|distributor)$")] = "technician",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    """List all technicians or distributors from the Pinecone geo index."""
    namespace = "technicians" if record_type == "technician" else "distributors"
    name_field = "technician_name" if record_type == "technician" else "distributor_name"
    loop = asyncio.get_event_loop()
    index = _get_geo_index()

    def _list_and_fetch():
        stats = index.describe_index_stats()
        total = 0
        if namespace in stats.namespaces:
            total = stats.namespaces[namespace].vector_count

        ids = []
        for id_batch in index.list(namespace=namespace):
            ids.extend(id_batch)
            if len(ids) >= limit:
                break
        ids = ids[:limit]
        if not ids:
            return total, []

        fetched = index.fetch(ids=ids, namespace=namespace)
        records = []
        for vec_id, vec in fetched.vectors.items():
            meta = vec.metadata or {}
            lat, lon = None, None
            if vec.values and len(vec.values) == 3:
                lat, lon = _xyz_to_latlon(*vec.values)
            records.append({
                "id": vec_id,
                "name": meta.get(name_field, "Unknown"),
                "phone": meta.get("phone_number", "N/A"),
                "address": meta.get("address", ""),
                "lat": lat,
                "lon": lon,
            })
        return total, records

    total, raw = await loop.run_in_executor(None, _list_and_fetch)
    records = [
        LocationRecord(id=r["id"], record_type=record_type, name=r["name"],
                       phone=r["phone"], address=r["address"], lat=r["lat"], lon=r["lon"])
        for r in raw
    ]
    return LocationsListResponse(record_type=record_type, total=total, records=records)


@router.post("/locations", response_model=AddLocationResponse, status_code=status.HTTP_201_CREATED)
async def add_location(payload: AddLocationRequest):
    """
    Geocode the provided address, compute a unit-sphere vector, and upsert
    the record into the Pinecone geo index under the appropriate namespace.
    """
    try:
        async with Nominatim(
            user_agent="HVACVoiceAgent/1.0", adapter_factory=AioHTTPAdapter
        ) as geolocator:
            location = await geolocator.geocode(payload.address + ", USA")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Geocoding request failed: {exc}",
        )

    if not location:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not geocode address: {payload.address!r}. Try a more specific address.",
        )

    phi = math.radians(location.latitude)
    lam = math.radians(location.longitude)
    vector = [
        math.cos(phi) * math.cos(lam),
        math.cos(phi) * math.sin(lam),
        math.sin(phi),
    ]

    namespace = "technicians" if payload.record_type == "technician" else "distributors"
    name_field = "technician_name" if payload.record_type == "technician" else "distributor_name"
    record_id = str(uuid.uuid4())
    metadata = {
        name_field: payload.name,
        "phone_number": payload.phone,
        "address": payload.address,
    }

    loop = asyncio.get_event_loop()
    index = _get_geo_index()

    def _upsert():
        index.upsert(
            vectors=[{"id": record_id, "values": vector, "metadata": metadata}],
            namespace=namespace,
        )

    await loop.run_in_executor(None, _upsert)
    lat, lon = _xyz_to_latlon(*vector)
    logger.info(
        "Location added | type=%s name=%s id=%s lat=%.4f lon=%.4f",
        payload.record_type, payload.name, record_id, lat, lon,
    )
    return AddLocationResponse(
        id=record_id,
        record_type=payload.record_type,
        name=payload.name,
        phone=payload.phone,
        address=payload.address,
        lat=lat,
        lon=lon,
    )


@router.put("/locations/{record_id}", response_model=AddLocationResponse)
async def update_location(
    record_id: str,
    payload: UpdateLocationRequest,
    record_type: Annotated[str, Query(pattern="^(technician|distributor)$")] = "technician",
):
    """
    Update a technician or distributor record.

    Fetches the existing vector first. Re-geocodes only when the address has
    actually changed; otherwise reuses the stored vector so name/phone-only
    edits never trigger a geocoding call.
    """
    namespace = "technicians" if record_type == "technician" else "distributors"
    name_field = "technician_name" if record_type == "technician" else "distributor_name"
    loop = asyncio.get_event_loop()
    index = _get_geo_index()

    # Fetch existing vector to compare address and reuse coordinates if unchanged.
    def _fetch():
        result = index.fetch(ids=[record_id], namespace=namespace)
        return result.vectors.get(record_id)

    existing = await loop.run_in_executor(None, _fetch)
    existing_address = (existing.metadata or {}).get("address", "") if existing else None
    existing_vector = existing.values if existing else None

    if payload.address != existing_address or existing_vector is None:
        # Address changed (or record not found) — re-geocode.
        try:
            async with Nominatim(
                user_agent="HVACVoiceAgent/1.0", adapter_factory=AioHTTPAdapter
            ) as geolocator:
                location = await geolocator.geocode(payload.address + ", USA")
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Geocoding request failed: {exc}",
            )

        if not location:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not geocode address: {payload.address!r}. Try a more specific address.",
            )

        phi = math.radians(location.latitude)
        lam = math.radians(location.longitude)
        vector = [
            math.cos(phi) * math.cos(lam),
            math.cos(phi) * math.sin(lam),
            math.sin(phi),
        ]
    else:
        vector = existing_vector

    metadata = {
        name_field: payload.name,
        "phone_number": payload.phone,
        "address": payload.address,
    }

    def _upsert():
        index.upsert(
            vectors=[{"id": record_id, "values": vector, "metadata": metadata}],
            namespace=namespace,
        )

    await loop.run_in_executor(None, _upsert)
    lat, lon = _xyz_to_latlon(*vector)
    logger.info(
        "Location updated | type=%s name=%s id=%s lat=%.4f lon=%.4f",
        record_type, payload.name, record_id, lat, lon,
    )
    return AddLocationResponse(
        id=record_id,
        record_type=record_type,
        name=payload.name,
        phone=payload.phone,
        address=payload.address,
        lat=lat,
        lon=lon,
    )


@router.delete("/locations/{record_id}", response_model=DeleteLocationResponse)
async def delete_location(
    record_id: str,
    record_type: Annotated[str, Query(pattern="^(technician|distributor)$")] = "technician",
):
    """Delete a technician or distributor record from the Pinecone geo index by vector ID."""
    namespace = "technicians" if record_type == "technician" else "distributors"
    loop = asyncio.get_event_loop()
    index = _get_geo_index()

    def _delete():
        index.delete(ids=[record_id], namespace=namespace)

    await loop.run_in_executor(None, _delete)
    logger.info("Location deleted | type=%s id=%s", record_type, record_id)
    return DeleteLocationResponse(id=record_id, record_type=record_type)
