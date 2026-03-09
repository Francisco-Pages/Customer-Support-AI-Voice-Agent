"""
RAG retriever — Pattern 2 (automatic pre-retrieval).

How it fits in the pipeline:
  User speech → VAD → STT → on_user_turn_completed()
                                 ├── embed(user_utterance)
                                 ├── Pinecone.query(vector, namespaces) [parallel]
                                 └── inject top-k passages into turn_ctx
                             → LLM sees system_prompt + injected context + transcript
                             → one-shot grounded answer (no extra round-trip)

Index layout (index: "ai-agent"):
  namespace                 vectors    content
  ───────────────────────────────────────────────────────────
  unit-specs                   779     product specifications
  warranty-policy-details       90     warranty terms
  error-codes                  132     error code reference
  common-troubleshooting        15     common fixes

All metadata records have a "content" field containing the passage text.

Redis is used as a query cache (TTL = 1 hour) so repeated / similar questions
are served instantly without hitting Pinecone or the embedding API.

Public API
----------
    retrieve(query, top_k) -> str

    Returns a formatted string of top-k passages ready to inject into the
    chat context, or an empty string when no relevant content was found.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from functools import partial

import redis.asyncio as aioredis
from openai import AsyncOpenAI
from pinecone import Pinecone

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Index configuration
# ---------------------------------------------------------------------------

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIMENSIONS = 1536
_CACHE_TTL_SEC = 3_600  # 1 hour

# Conversational filler words that never need a knowledge base lookup.
# If the entire utterance (lowercased, stripped) matches one of these,
# RAG is skipped entirely — saving one embedding call + 4 Pinecone queries.
_FILLER_TURNS = {
    "yes", "no", "yeah", "nope", "yep", "nah",
    "ok", "okay", "sure", "alright", "fine",
    "got it", "i see", "i got it", "understood",
    "thank you", "thanks", "thank you so much", "thanks a lot",
    "hold on", "one moment", "one sec", "one second", "just a moment",
    "hello", "hi", "hey",
    "bye", "goodbye", "good bye",
    "that's all", "thats all", "nothing else", "no thanks", "no thank you",
    "not yet", "not really", "not sure", "maybe",
    "go ahead", "please", "please go ahead",
    "correct", "that's correct", "thats correct", "yes that's correct",
    "yes that's right", "that's right", "thats right",
    "sounds good", "sounds great", "perfect", "great",
    "email", "text", "sms", "both",
    "email please", "text please", "sms please",
    "yes email", "yes text", "yes sms",
    "email works", "text works", "either is fine",
    # Transfer / escalation intent — no product knowledge needed.
    "transfer me", "transfer me to an agent", "transfer me to a human",
    "speak to an agent", "speak to a person", "speak to a human",
    "speak to a representative", "talk to an agent", "talk to a person",
    "talk to a human", "talk to a representative",
    "i want to speak to a human", "i want to talk to a human",
    "i want to speak to an agent", "i want to talk to an agent",
    "connect me to an agent", "connect me to a human",
    "give me a human", "get me a human", "get me an agent",
    "live agent", "live person", "real person", "actual person",
}

# Queries matching this pattern carry no technical content — skip RAG entirely.
# Checked after _FILLER_TURNS so exact-match short-circuits first.
_SKIP_RAG_PATTERN = re.compile(
    r"\b("
    # Transfer / escalation
    r"transfer|escalat|speak\s+to|talk\s+to|connect\s+me|give\s+me|get\s+me"
    r")\b.{0,40}\b(agent|human|person|representative|rep|specialist|someone)\b"
    r"|"
    # Document / email / SMS delivery requests
    r"\b(send|email|text|sms|document|manual|leaflet|brochure|spec\s+sheet|"
    r"installation\s+guide|send\s+me|email\s+me|text\s+me)\b.{0,60}"
    r"\b(manual|leaflet|document|brochure|guide|catalog|catalogue|spec|link)\b"
    r"|"
    # Asking for email / contact collection
    r"\bmy\s+(email|e-mail|email\s+address)\s+is\b"
    r"|"
    # Name / city / state giving — pure info collection, no KB needed
    r"\bmy\s+name\s+is\b"
    r"|\bi('?m| am)\s+(?:calling\s+from\s+)?[A-Z][a-z]"
    r"|\bI'?m\s+in\s+[A-Z]"
    r"|\bI\s+live\s+in\b"
    r"|\bI('?m| am)\s+from\b",
    re.IGNORECASE,
)

# All namespaces — used as the fallback when no routing rule matches.
_ALL_NAMESPACES = [
    "unit-specs",
    "warranty-policy-details",
    "error-codes",
    "common-troubleshooting",
]

# ---------------------------------------------------------------------------
# Namespace routing
#
# Each rule is a (compiled_regex, [namespaces]) pair. The query is matched
# against rules in order; all matching rules contribute their namespaces.
# If no rule fires, _ALL_NAMESPACES is used as a safe fallback.
#
# Keeping this as a plain list makes it easy to add/adjust rules without
# touching any other code.
# ---------------------------------------------------------------------------

_NS_UNIT_SPECS = "unit-specs"
_NS_WARRANTY = "warranty-policy-details"
_NS_ERROR_CODES = "error-codes"
_NS_TROUBLESHOOTING = "common-troubleshooting"

_ROUTING_RULES: list[tuple[re.Pattern, list[str]]] = [
    (
        re.compile(
            r"\b("
            r"model|serial|btu|ton(?:s|nage)?|refrigerant|r-?4(?:10a?|54b?|32)|"
            r"indoor|outdoor|unit|compatibl|line\s*set|capacity|zone|"
            r"install|combination|multi.?zone|single.?zone|"
            r"ch-|os-|brv-|astoria|olivia|sophia|bravo|olmo|"
            r"spec(?:s|ification)?|watt|amp|voltage|phase|clearance|dimension"
            r")\b",
            re.IGNORECASE,
        ),
        [_NS_UNIT_SPECS],
    ),
    (
        re.compile(
            r"\b("
            r"warrant(?:y|ies)|cover(?:age|ed)|register|registration|"
            r"claim|years?\s+warrant|parts?\s+warrant|compressor\s+warrant|"
            r"what(?:'s|\s+is)\s+covered|extended\s+warrant|expire"
            r")\b",
            re.IGNORECASE,
        ),
        [_NS_WARRANTY],
    ),
    (
        re.compile(
            r"\b("
            r"error\s*code|fault\s*code|e\d+|f\d+|"
            r"flash(?:ing)?|blink(?:ing)?|display(?:\s+shows?)?|"
            r"code\s+on|shows?\s+(?:an?\s+)?(?:error|fault|code)"
            r")\b",
            re.IGNORECASE,
        ),
        [_NS_ERROR_CODES],
    ),
    (
        re.compile(
            r"\b("
            r"not\s+(?:cool|heat|work|turn|run)|won'?t\s+(?:cool|heat|start|turn)|"
            r"warm\s+air|no\s+(?:cool|heat|air)|ice\s+on|frost(?:ing)?|"
            r"leak(?:ing)?|noise|sound|vibrat|filter|breaker|trip(?:ping)?|"
            r"short\s*cycl|blow(?:ing)?\s+warm|not\s+enough\s+(?:cool|heat)|"
            r"trouble|problem|issue|broken|not\s+work|doesn'?t\s+work"
            r")\b",
            re.IGNORECASE,
        ),
        [_NS_TROUBLESHOOTING],
    ),
]


def _route_namespaces(query: str) -> list[str]:
    """
    Return the namespaces to query for a given user utterance.
    Matches all applicable routing rules and deduplicates.
    Falls back to all namespaces if nothing matches.
    """
    matched: list[str] = []
    for pattern, namespaces in _ROUTING_RULES:
        if pattern.search(query):
            for ns in namespaces:
                if ns not in matched:
                    matched.append(ns)
    if not matched:
        logger.debug("RAG routing: no rule matched — querying all namespaces")
        return _ALL_NAMESPACES
    logger.debug("RAG routing: %s → %s", query[:60], matched)
    return matched

# ---------------------------------------------------------------------------
# Lazy-initialised module-level clients
#
# Initialised on first use rather than at import time so that:
#   - The agent worker can import this module before settings are loaded
#   - Tests can monkey-patch settings before the first call
# ---------------------------------------------------------------------------

_pinecone_client: Pinecone | None = None
_pinecone_index = None  # cached Index object — built once, reused across all queries
_openai_client: AsyncOpenAI | None = None
_redis_client: aioredis.Redis | None = None

# ---------------------------------------------------------------------------
# Redis circuit-breaker
#
# After any Redis error, cache operations are skipped for _REDIS_RETRY_SEC.
# This prevents a full traceback from being logged on every single RAG call
# when Redis is unavailable. A single WARNING is logged on first failure;
# an INFO is logged when the circuit closes again (Redis comes back).
# ---------------------------------------------------------------------------

_REDIS_RETRY_SEC = 60
_redis_open_until: float = 0.0  # monotonic; 0 = circuit closed (healthy)


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


async def _redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
    return _redis_client


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(query: str, namespaces: list[str]) -> str:
    """Stable 16-char hash of (query, namespaces) used as the Redis key."""
    payload = json.dumps({"q": query, "ns": sorted(namespaces)}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"rag:{digest}"


def _redis_tripped() -> bool:
    """Return True if the circuit-breaker is open (Redis known-unavailable)."""
    return time.monotonic() < _redis_open_until


def _trip_redis(exc: Exception) -> None:
    """Open the circuit-breaker and emit a single WARNING."""
    global _redis_open_until
    was_healthy = not _redis_tripped()
    _redis_open_until = time.monotonic() + _REDIS_RETRY_SEC
    if was_healthy:
        logger.warning(
            "Redis unavailable — cache disabled for %ds | %s: %s",
            _REDIS_RETRY_SEC,
            type(exc).__name__,
            exc,
        )


def _reset_redis() -> None:
    """Close the circuit-breaker and emit an INFO on recovery."""
    global _redis_open_until
    if _redis_tripped():
        logger.info("Redis reconnected — cache re-enabled")
    _redis_open_until = 0.0


async def _cache_get(key: str) -> str | None:
    if _redis_tripped():
        return None
    try:
        client = await _redis()
        result = await client.get(key)
        _reset_redis()
        return result
    except Exception as exc:
        _trip_redis(exc)
        return None


async def _cache_set(key: str, value: str) -> None:
    if _redis_tripped():
        return
    try:
        client = await _redis()
        await client.setex(key, _CACHE_TTL_SEC, value)
        _reset_redis()
    except Exception as exc:
        _trip_redis(exc)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


async def _embed(text: str) -> list[float]:
    response = await _oai().embeddings.create(
        input=text,
        model=_EMBEDDING_MODEL,
        dimensions=_EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding


# ---------------------------------------------------------------------------
# Pinecone query
#
# pinecone-client 5.x is synchronous, so each namespace query runs in a
# thread executor. All namespace queries are launched concurrently via
# asyncio.gather so total wall-clock time ≈ single namespace latency.
# ---------------------------------------------------------------------------


def _query_namespace_sync(
    vector: list[float],
    namespace: str,
    top_k: int,
) -> list[tuple[float, str]]:
    """
    Query a single Pinecone namespace synchronously.
    Returns a list of (score, passage_text) tuples.
    Always called via run_in_executor.
    """
    results = _index().query(
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )
    passages: list[tuple[float, str]] = []
    for match in results.matches:
        if match.metadata:
            text = match.metadata.get("content", "").strip()
            if text:
                passages.append((match.score, text))
    return passages


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def retrieve(
    query: str,
    top_k: int = 5,
) -> str:
    """
    Retrieve the most relevant HVAC knowledge base passages for a user query.

    Called inside HVACAssistant.on_user_turn_completed() on every user turn.
    The returned string is injected into the chat context as an assistant
    message before the LLM generates its response.

    Queries all configured namespaces in parallel, merges results by
    relevance score, and returns the top-k passages as a formatted string.

    Args:
        query:  The user's utterance (raw STT transcript).
        top_k:  Total number of passages to return after merging (default 5).

    Returns:
        A newline-separated string of relevant passages,
        or an empty string when no results are found.
    """
    query = query.strip()
    if not query:
        return ""

    # Skip RAG for short conversational turns that carry no technical content.
    # This avoids one embedding call + 4 Pinecone queries on acknowledgements,
    # confirmations, and filler responses where injected context adds no value.
    _normalized = query.lower().strip("?.!,")
    if _normalized in _FILLER_TURNS:
        logger.debug("RAG skipped — conversational turn | query=%r", query)
        return ""

    if _SKIP_RAG_PATTERN.search(query):
        logger.debug("RAG skipped — transfer/escalation intent | query=%r", query)
        return ""

    namespaces = _route_namespaces(query)
    cache_key = _cache_key(query, namespaces)

    # 1. Cache lookup
    cached = await _cache_get(cache_key)
    if cached is not None:
        logger.debug("RAG cache hit | key=%s", cache_key)
        return cached

    # 2. Embed the query
    vector = await _embed(query)

    # 3. Query routed namespaces concurrently
    #    Each namespace runs in a thread (sync SDK); asyncio.gather runs them in parallel.
    per_ns = max(3, top_k)
    loop = asyncio.get_event_loop()
    ns_results: list[list[tuple[float, str]]] = await asyncio.gather(
        *[
            loop.run_in_executor(
                None,
                partial(_query_namespace_sync, vector, ns, per_ns),
            )
            for ns in namespaces
        ]
    )

    # 4. Merge all results, sort by score descending, take top-k
    all_passages: list[tuple[float, str]] = [
        item for ns_list in ns_results for item in ns_list
    ]
    all_passages.sort(key=lambda x: x[0], reverse=True)
    top_passages = [text for _, text in all_passages[:top_k]]

    if not top_passages:
        logger.debug("RAG: no passages found | query=%r", query[:80])
        return ""

    context = "\n\n".join(top_passages)

    # 5. Cache the result
    await _cache_set(cache_key, context)

    logger.info(
        "RAG retrieved %d passages from %s | query=%r",
        len(top_passages),
        namespaces,
        query[:80],
    )
    return context
