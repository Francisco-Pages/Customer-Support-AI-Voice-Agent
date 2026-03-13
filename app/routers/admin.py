"""
Admin REST API.

All endpoints require the X-Api-Key header matching ADMIN_API_KEY in settings.
No customer-facing or Twilio-facing logic lives here — this is purely for
internal operations: launching outbound campaigns, querying call records,
and managing the outbound queue.
"""

import asyncio
import json
import logging
import math
import uuid
from datetime import datetime
from typing import Annotated
from uuid import UUID

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from geopy.adapters import AioHTTPAdapter
from geopy.geocoders import Nominatim
from openai import AsyncOpenAI
from pinecone import Pinecone
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agent.prompts import INBOUND_SYSTEM_PROMPT, build_inbound_prompt
from app.config import settings
from app.core.security import verify_admin_api_key
from app.dependencies import get_db, get_redis
from app.rag.ingestor import delete_document, ingest_document
from app.services import call as call_service
from app.services import campaign as campaign_service
from app.services import customer as customer_service
from app.services import geo as geo_service
from app.services import parts as parts_service

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
    has_recording: bool
    recording_sid: str | None


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
        has_recording=bool(call.recording_sid),
        recording_sid=call.recording_sid,
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
# Customers
# ---------------------------------------------------------------------------


class CustomerRecord(BaseModel):
    id: UUID
    phone: str
    name: str | None
    email: str | None
    address: str | None
    caller_type: str | None
    tcpa_consent: bool
    created_at: str
    updated_at: str


class CustomerListResponse(BaseModel):
    total: int
    customers: list[CustomerRecord]


class CreateCustomerRequest(BaseModel):
    phone: str = Field(..., min_length=1)
    name: str | None = None
    email: str | None = None
    address: str | None = None
    caller_type: str | None = Field(None, pattern="^(owner|technician)$")
    tcpa_consent: bool = False


class UpdateCustomerRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    address: str | None = None
    caller_type: str | None = Field(None, pattern="^(owner|technician)$")
    tcpa_consent: bool | None = None


def _customer_to_record(c) -> CustomerRecord:
    return CustomerRecord(
        id=c.id,
        phone=c.phone,
        name=c.name,
        email=c.email,
        address=c.address,
        caller_type=c.caller_type,
        tcpa_consent=c.tcpa_consent,
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
    )


@router.get("/customers", response_model=CustomerListResponse)
async def list_customers(
    search: Annotated[str | None, Query(description="Search by phone, name, or email")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
):
    """Paginated customer list with optional search."""
    total, customers = await customer_service.list_customers(db, search=search, limit=limit, offset=offset)
    return CustomerListResponse(total=total, customers=[_customer_to_record(c) for c in customers])


@router.get("/customers/{customer_id}", response_model=CustomerRecord)
async def get_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve a single customer by UUID."""
    c = await customer_service.get_by_id(db, customer_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    return _customer_to_record(c)


@router.post("/customers", response_model=CustomerRecord, status_code=status.HTTP_201_CREATED)
async def create_customer(payload: CreateCustomerRequest, db: AsyncSession = Depends(get_db)):
    """Create a new customer record."""
    existing = await customer_service.get_by_phone(db, payload.phone)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A customer with that phone number already exists.")
    c = await customer_service.create(
        db,
        phone=payload.phone,
        name=payload.name,
        email=payload.email,
        address=payload.address,
        caller_type=payload.caller_type,
        tcpa_consent=payload.tcpa_consent,
    )
    return _customer_to_record(c)


@router.put("/customers/{customer_id}", response_model=CustomerRecord)
async def update_customer(
    customer_id: UUID,
    payload: UpdateCustomerRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a customer's details."""
    from app.db.models import Customer as CustomerModel
    c = await customer_service.get_by_id(db, customer_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    if payload.name is not None:
        c.name = payload.name
    if payload.email is not None:
        c.email = payload.email
    if payload.address is not None:
        c.address = payload.address
    if payload.caller_type is not None:
        c.caller_type = payload.caller_type
    if payload.tcpa_consent is not None:
        c.tcpa_consent = payload.tcpa_consent
    await db.flush()
    await db.refresh(c)
    return _customer_to_record(c)


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(customer_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a customer and all their associated records."""
    deleted = await customer_service.delete(db, customer_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")


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


@router.get("/calls/{call_id}/recording")
async def get_call_recording(call_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Proxy the Twilio recording MP3 to the browser.

    Twilio requires HTTP Basic auth to access recordings. This endpoint
    fetches the audio server-side and streams it so the browser doesn't
    need to know the Twilio credentials.
    """
    call = await call_service.get_by_id(db, call_id)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found.")
    if not call.recording_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No recording available.")

    # Twilio recording URLs end with no extension; append .mp3 for direct playback.
    url = call.recording_url
    if not url.endswith(".mp3"):
        url = url + ".mp3"

    async def _stream():
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "GET",
                url,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                timeout=30,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    yield chunk

    return StreamingResponse(_stream(), media_type="audio/mpeg")


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


class ValidateDocumentResponse(BaseModel):
    match: bool          # True = content fits the namespace
    confidence: str      # "high" | "medium" | "low"
    detected_type: str   # e.g. "error code reference"
    reason: str          # one-sentence explanation


_NAMESPACE_DESCRIPTIONS = {
    "unit-specs": "product specifications (model numbers, BTU ratings, dimensions, refrigerant types, technical capacities)",
    "warranty-policy-details": "warranty policy (coverage terms, duration, registration requirements, exclusions)",
    "error-codes": "error code reference (fault codes shown on unit display, diagnostic codes with descriptions)",
    "common-troubleshooting": "troubleshooting guide (step-by-step fixes, common HVAC problems and solutions)",
}

_CLASSIFY_PROMPT = """\
You are classifying an HVAC document to determine which knowledge base namespace it belongs to.

Namespaces:
- unit-specs: {unit_specs}
- warranty-policy-details: {warranty}
- error-codes: {error_codes}
- common-troubleshooting: {troubleshooting}

Respond ONLY with valid JSON (no markdown, no extra text):
{{"category": "<namespace>", "confidence": "high|medium|low", "reason": "<one sentence>"}}

Document excerpt:
{excerpt}
"""


@router.post("/documents/validate", response_model=ValidateDocumentResponse)
async def validate_document_endpoint(
    file: UploadFile,
    namespace: Annotated[
        str,
        Query(description="Target namespace to validate against"),
    ],
):
    """
    Pre-flight check: parse the uploaded file and ask GPT-4o-mini whether
    its content matches the selected namespace.  Returns match=True/False,
    confidence, detected type, and a one-sentence reason.

    This endpoint does NOT write anything to Pinecone.
    """
    if namespace not in _VALID_NAMESPACES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid namespace '{namespace}'.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    filename = file.filename or "upload"

    from app.rag.ingestor import parse_file
    try:
        text = parse_file(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # Use the first 1 500 characters as the classification sample
    excerpt = text.strip()[:1500]
    if not excerpt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No text could be extracted.")

    prompt = _CLASSIFY_PROMPT.format(
        unit_specs=_NAMESPACE_DESCRIPTIONS["unit-specs"],
        warranty=_NAMESPACE_DESCRIPTIONS["warranty-policy-details"],
        error_codes=_NAMESPACE_DESCRIPTIONS["error-codes"],
        troubleshooting=_NAMESPACE_DESCRIPTIONS["common-troubleshooting"],
        excerpt=excerpt,
    )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("Document classification failed | file=%s error=%s", filename, exc)
        # If classification fails, allow upload with low confidence
        return ValidateDocumentResponse(
            match=True,
            confidence="low",
            detected_type="unknown",
            reason="Classification unavailable — content could not be automatically verified.",
        )

    detected = parsed.get("category", "")
    confidence = parsed.get("confidence", "low")
    reason = parsed.get("reason", "")
    match = detected == namespace

    return ValidateDocumentResponse(
        match=match,
        confidence=confidence,
        detected_type=_NAMESPACE_DESCRIPTIONS.get(detected, detected),
        reason=reason,
    )


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


# ---------------------------------------------------------------------------
# Agent chat (test interface)
# ---------------------------------------------------------------------------

_CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_parts_availability",
            "description": "Look up replacement part numbers compatible with a customer's HVAC unit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_model": {"type": "string", "description": "Customer's HVAC unit model number"},
                    "part_type": {"type": "string", "description": "Type of part, e.g. Fan Motor"},
                    "part_name": {"type": "string", "description": "Specific part name if known"},
                },
                "required": ["product_model"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_customer",
            "description": "Look up a customer record by phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "E.164 phone number, e.g. +13055551234"},
                },
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_warranty",
            "description": "Look up warranty status for a registered product by serial number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "serial_number": {"type": "string"},
                },
                "required": ["serial_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_technicians",
            "description": "Find certified HVAC technicians near a city and state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                },
                "required": ["city", "state"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_distributors",
            "description": "Find HVAC distributors near a city and state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                },
                "required": ["city", "state"],
            },
        },
    },
]


async def _execute_tool(name: str, args: dict, db: AsyncSession) -> str:
    """Dispatch a tool call to the real service layer and return a string result."""
    if name == "check_parts_availability":
        matches = await parts_service.lookup_parts(
            db,
            product_model=args["product_model"],
            part_type=args.get("part_type"),
            part_name=args.get("part_name"),
        )
        if not matches:
            return "No matching parts found in the catalog."
        seen: set[str] = set()
        lines = []
        for m in matches:
            if m["part_number"] not in seen:
                seen.add(m["part_number"])
                lines.append(
                    f"Part number: {m['part_number']} — {m['part_name']} "
                    f"({m['part_type']}, {m['brand']}) matched model: {m['matched_model']}"
                )
        return "\n".join(lines)

    if name == "lookup_customer":
        customer = await customer_service.get_by_phone_with_products(db, args["phone"])
        if not customer:
            return "No customer record found for that phone number."
        products = ", ".join(p.product_model for p in customer.products) or "none"
        return (
            f"Customer: {customer.name or 'Unknown'}, phone: {customer.phone}, "
            f"email: {customer.email or 'N/A'}, registered products: {products}"
        )

    if name == "lookup_warranty":
        from sqlalchemy import select
        from app.db.models import CustomerProduct
        from datetime import timezone

        sn = args["serial_number"]
        result = await db.execute(
            select(CustomerProduct).where(CustomerProduct.serial_number == sn)
        )
        product = result.scalar_one_or_none()
        if not product:
            return f"No product registered with serial number {sn}."
        if not product.warranty_end_date:
            return f"Product {product.product_model} (SN: {sn}) has no warranty date on file."
        now = datetime.now(timezone.utc)
        exp = product.warranty_end_date
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > now:
            return (
                f"Product {product.product_model} (SN: {sn}) is under warranty. "
                f"Expires {exp.strftime('%B %d, %Y')} ({(exp - now).days} days remaining)."
            )
        return (
            f"Product {product.product_model} (SN: {sn}) — "
            f"warranty expired on {exp.strftime('%B %d, %Y')}."
        )

    if name == "search_technicians":
        results = await geo_service.search(args["city"], args["state"], "technician")
        if not results:
            return "No technicians found near that location."
        return "\n".join(
            f"{r.get('name', 'Unknown')} — {r.get('phone', 'N/A')} — {r.get('address', '')}"
            for r in results
        )

    if name == "search_distributors":
        results = await geo_service.search(args["city"], args["state"], "distributor")
        if not results:
            return "No distributors found near that location."
        return "\n".join(
            f"{r.get('name', 'Unknown')} — {r.get('phone', 'N/A')} — {r.get('address', '')}"
            for r in results
        )

    return f"Unknown tool: {name}"


class ChatMessageModel(BaseModel):
    role: str
    content: str


class ToolCallInfo(BaseModel):
    name: str
    args: dict
    result: str


class ChatRequest(BaseModel):
    message: str
    messages: list[ChatMessageModel] = []
    phone: str | None = None


class ChatResponse(BaseModel):
    reply: str
    messages: list[ChatMessageModel]
    tool_calls: list[ToolCallInfo]


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Send a message to the agent and get a reply.

    The caller maintains conversation history and sends it back with each
    request. Tool calls are executed server-side using real services and
    returned for display alongside the agent reply.
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    system = INBOUND_SYSTEM_PROMPT
    if payload.phone:
        system += f"\n\n[TEST SESSION] Caller phone: {payload.phone}"

    openai_messages: list[dict] = [{"role": "system", "content": system}]
    for m in payload.messages:
        openai_messages.append({"role": m.role, "content": m.content})
    openai_messages.append({"role": "user", "content": payload.message})

    tool_calls_made: list[ToolCallInfo] = []

    for _ in range(8):  # max agentic iterations
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=openai_messages,
            tools=_CHAT_TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            reply = msg.content or ""
            updated_messages = [
                ChatMessageModel(role=m["role"], content=m["content"])
                for m in openai_messages[1:]  # drop system prompt
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            updated_messages.append(ChatMessageModel(role="assistant", content=reply))
            return ChatResponse(
                reply=reply,
                messages=updated_messages,
                tool_calls=tool_calls_made,
            )

        # Append assistant message with tool_calls
        openai_messages.append(msg.model_dump(exclude_unset=True))

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            result = await _execute_tool(tc.function.name, args, db)
            tool_calls_made.append(ToolCallInfo(name=tc.function.name, args=args, result=result))
            openai_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    raise HTTPException(status_code=500, detail="Agent did not produce a final reply.")


# ---------------------------------------------------------------------------
# Prompt management
# ---------------------------------------------------------------------------

_PROMPT_REDIS_KEY = "prompt:inbound"


class PromptResponse(BaseModel):
    prompt: str
    is_custom: bool   # False = file default, True = stored override


class PromptUpdateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


@router.get("/prompt", response_model=PromptResponse)
async def get_prompt(redis: aioredis.Redis = Depends(get_redis)):
    """Return the current inbound system prompt (custom override or file default)."""
    stored = await redis.get(_PROMPT_REDIS_KEY)
    if stored:
        return PromptResponse(prompt=stored, is_custom=True)
    return PromptResponse(
        prompt=build_inbound_prompt(settings.linq_from_number),
        is_custom=False,
    )


@router.put("/prompt", response_model=PromptResponse)
async def update_prompt(
    payload: PromptUpdateRequest,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Save a custom inbound system prompt. Takes effect on the next call."""
    await redis.set(_PROMPT_REDIS_KEY, payload.prompt)
    return PromptResponse(prompt=payload.prompt, is_custom=True)


@router.delete("/prompt", status_code=status.HTTP_204_NO_CONTENT)
async def reset_prompt(redis: aioredis.Redis = Depends(get_redis)):
    """Delete the custom prompt override, reverting to the file default."""
    await redis.delete(_PROMPT_REDIS_KEY)


# ---------------------------------------------------------------------------
# Agent settings (temperature, etc.)
# ---------------------------------------------------------------------------

_SETTINGS_REDIS_KEY = "agent:settings"
_DEFAULT_TEMPERATURE = 0.1
_DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"  # ElevenLabs "Sarah"


class AgentSettingsResponse(BaseModel):
    temperature: float
    voice_id: str


class AgentSettingsUpdateRequest(BaseModel):
    temperature: float = Field(..., ge=0.0, le=2.0)
    voice_id: str = Field(..., min_length=1)


@router.get("/settings", response_model=AgentSettingsResponse)
async def get_agent_settings(redis: aioredis.Redis = Depends(get_redis)):
    """Return current agent settings."""
    stored = await redis.hgetall(_SETTINGS_REDIS_KEY)
    temperature = float(stored["temperature"]) if stored.get("temperature") else _DEFAULT_TEMPERATURE
    voice_id = stored.get("voice_id") or _DEFAULT_VOICE_ID
    return AgentSettingsResponse(temperature=temperature, voice_id=voice_id)


@router.put("/settings", response_model=AgentSettingsResponse)
async def update_agent_settings(
    payload: AgentSettingsUpdateRequest,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Update agent settings. Takes effect on the next call."""
    await redis.hset(_SETTINGS_REDIS_KEY, mapping={
        "temperature": payload.temperature,
        "voice_id": payload.voice_id,
    })
    return AgentSettingsResponse(temperature=payload.temperature, voice_id=payload.voice_id)
