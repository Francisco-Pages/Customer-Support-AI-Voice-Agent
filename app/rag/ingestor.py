"""
Document ingestion pipeline for the HVAC knowledge base.

Flow:
  Upload file → parse text → chunk with overlap → batch embed → upsert to Pinecone

Supported file types: .txt, .md, .pdf, .docx

Vector ID format: {doc_id}_{chunk_index}
  where doc_id = sha256(original_filename)[:12]

This allows clean re-ingestion: upserting the same filename overwrites all
existing vectors for that document without leaving orphans.

Metadata stored per vector:
  content      - passage text (read by retriever)
  source       - original filename
  doc_id       - stable 12-char document identifier
  chunk_index  - 0-based position within the document
"""

import asyncio
import hashlib
import io
import logging
from dataclasses import dataclass
from functools import partial

from openai import AsyncOpenAI
from pinecone import Pinecone

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chunking config
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 1_500     # characters (~375 tokens)
_CHUNK_OVERLAP = 200    # characters of overlap between consecutive chunks

# Ordered separators for recursive splitting
_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]

# ---------------------------------------------------------------------------
# Embedding config (mirrors retriever.py)
# ---------------------------------------------------------------------------

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIMENSIONS = 1536
_EMBED_BATCH_SIZE = 100   # OpenAI allows up to 2048; keep well below for safety

# ---------------------------------------------------------------------------
# Lazy clients
# ---------------------------------------------------------------------------

_pinecone_client: Pinecone | None = None
_pinecone_index = None
_openai_client: AsyncOpenAI | None = None


def _pc() -> Pinecone:
    global _pinecone_client
    if _pinecone_client is None:
        _pinecone_client = Pinecone(api_key=settings.pinecone_api_key)
    return _pinecone_client


def _index():
    global _pinecone_index
    if _pinecone_index is None:
        _pinecone_index = _pc().Index(settings.pinecone_index_name)
    return _pinecone_index


def _oai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------


def _parse_txt(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _parse_pdf(content: bytes) -> str:
    try:
        import pypdf  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF ingestion: pip install pypdf") from exc

    reader = pypdf.PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def _parse_docx(content: bytes) -> str:
    try:
        import docx  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is required for DOCX ingestion: pip install python-docx"
        ) from exc

    doc = docx.Document(io.BytesIO(content))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def parse_file(filename: str, content: bytes) -> str:
    """
    Extract plain text from an uploaded file.
    Raises ValueError for unsupported extensions.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("txt", "md"):
        return _parse_txt(content)
    if ext == "pdf":
        return _parse_pdf(content)
    if ext == "docx":
        return _parse_docx(content)
    raise ValueError(f"Unsupported file type: .{ext}. Supported: .txt .md .pdf .docx")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _split_on_separator(text: str, sep: str, chunk_size: int) -> list[str]:
    """Split text on sep, re-joining short pieces so chunks approach chunk_size."""
    if not sep:
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    pieces = text.split(sep)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = (current + sep + piece).lstrip(sep) if current else piece
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


def chunk_text(
    text: str,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> list[str]:
    """
    Recursively split text into overlapping chunks of approximately chunk_size
    characters, breaking on natural boundaries (paragraphs > sentences > words > chars).
    """
    text = text.strip()
    if not text:
        return []

    candidates: list[str] = [text]
    for sep in _SEPARATORS:
        candidates = _split_on_separator(text, sep, chunk_size)
        if all(len(c) <= chunk_size for c in candidates) or not sep:
            break

    if not candidates:
        return []

    final: list[str] = []
    for i, chunk in enumerate(candidates):
        if len(chunk) > chunk_size:
            final.extend(chunk_text(chunk, chunk_size, overlap))
        else:
            if i > 0 and overlap > 0:
                prev = candidates[i - 1]
                tail = prev[-overlap:] if len(prev) >= overlap else prev
                chunk = (tail + " " + chunk).strip()
                if len(chunk) > chunk_size:
                    chunk = chunk[-chunk_size:]
            final.append(chunk)

    return [c for c in final if c.strip()]


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------


async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed texts in batches of _EMBED_BATCH_SIZE."""
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i : i + _EMBED_BATCH_SIZE]
        response = await _oai().embeddings.create(
            input=batch,
            model=_EMBEDDING_MODEL,
            dimensions=_EMBEDDING_DIMENSIONS,
        )
        all_vectors.extend([item.embedding for item in response.data])
    return all_vectors


# ---------------------------------------------------------------------------
# Pinecone helpers (synchronous SDK → thread executor)
# ---------------------------------------------------------------------------


def _upsert_sync(vectors: list[dict], namespace: str) -> None:
    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        _index().upsert(vectors=vectors[i : i + batch_size], namespace=namespace)


def _delete_by_prefix_sync(doc_id: str, namespace: str) -> int:
    idx = _index()
    ids_to_delete: list[str] = []
    for page in idx.list(prefix=f"{doc_id}_", namespace=namespace):
        ids_to_delete.extend(page)
    if ids_to_delete:
        idx.delete(ids=ids_to_delete, namespace=namespace)
    return len(ids_to_delete)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    doc_id: str
    filename: str
    namespace: str
    chunks_ingested: int
    characters_total: int


async def ingest_document(
    content: bytes,
    filename: str,
    namespace: str,
) -> IngestResult:
    """
    Parse, chunk, embed, and upsert a document into Pinecone.

    Uses sha256(filename)[:12] as doc_id so re-uploading the same file
    overwrites existing vectors cleanly (upsert semantics).
    """
    doc_id = hashlib.sha256(filename.encode()).hexdigest()[:12]

    logger.info("Ingest started | file=%s doc_id=%s namespace=%s", filename, doc_id, namespace)

    text = parse_file(filename, content)
    if not text.strip():
        raise ValueError(f"No text could be extracted from '{filename}'.")

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError(f"Document '{filename}' produced no chunks after splitting.")

    logger.info("Ingest chunked | doc_id=%s chunks=%d", doc_id, len(chunks))

    vectors_data = await _embed_batch(chunks)

    records = [
        {
            "id": f"{doc_id}_{i}",
            "values": vec,
            "metadata": {
                "content": chunk,
                "source": filename,
                "doc_id": doc_id,
                "chunk_index": i,
            },
        }
        for i, (chunk, vec) in enumerate(zip(chunks, vectors_data))
    ]

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_upsert_sync, records, namespace))

    logger.info(
        "Ingest complete | doc_id=%s namespace=%s chunks=%d chars=%d",
        doc_id,
        namespace,
        len(chunks),
        len(text),
    )

    return IngestResult(
        doc_id=doc_id,
        filename=filename,
        namespace=namespace,
        chunks_ingested=len(chunks),
        characters_total=len(text),
    )


async def delete_document(doc_id: str, namespace: str) -> int:
    """
    Delete all vectors for a given doc_id from a Pinecone namespace.
    Returns the number of vectors deleted.
    """
    loop = asyncio.get_event_loop()
    deleted = await loop.run_in_executor(
        None, partial(_delete_by_prefix_sync, doc_id, namespace)
    )
    logger.info("Ingest delete | doc_id=%s namespace=%s deleted=%d", doc_id, namespace, deleted)
    return deleted
