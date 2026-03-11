"""
Ingest lamp-blink error codes into the existing error-codes Pinecone namespace.

These codes identify faults by the number of times the operation lamp flashes
combined with the state of the timer lamp (off / on / flashing).

The script APPENDS to the namespace — it does NOT delete existing vectors.

Usage:
    python scripts/ingest_lamp_error_codes.py ~/Downloads/light_error_codes.jsonl
    python scripts/ingest_lamp_error_codes.py ~/Downloads/light_error_codes.jsonl --dry-run
"""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

import os

from openai import AsyncOpenAI
from pinecone import Pinecone

NAMESPACE = "error-codes"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
BATCH_SIZE = 100


def record_to_text(op_flashes: int, timer_state: str, description: str) -> str:
    """
    Convert a lamp-blink record to a natural-language passage optimised for
    semantic search. A caller might say "my operation light blinks 5 times and
    the timer light is on" — the passage is written to match those queries.
    """
    flash_word = "time" if op_flashes == 1 else "times"
    timer_desc = {
        "off":      "timer lamp is OFF",
        "on":       "timer lamp is ON",
        "flashing": "timer lamp is FLASHING",
    }.get(timer_state.lower(), f"timer lamp is {timer_state.upper()}")

    return (
        f"Lamp blink error code: operation lamp flashes {op_flashes} {flash_word}, "
        f"{timer_desc}. "
        f"Fault: {description}"
    )


async def embed_batch(client: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = await client.embeddings.create(
            input=batch,
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        all_vectors.extend([item.embedding for item in response.data])
        print(f"  Embedded {min(i + BATCH_SIZE, len(texts))}/{len(texts)}", end="\r")
    print()
    return all_vectors


def upsert_batch(index, records: list[dict]):
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        index.upsert(vectors=batch, namespace=NAMESPACE)
        print(f"  Upserted {min(i + BATCH_SIZE, len(records))}/{len(records)}", end="\r")
    print()


async def main(jsonl_path: str, dry_run: bool):
    raw: list[dict] = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                raw.append(json.loads(line))

    print(f"Loaded {len(raw)} lamp-blink records from {jsonl_path}")

    passages = []
    for r in raw:
        op = int(r["operation_lamp"])
        timer = str(r["timer_lamp"])
        desc = r["error_code_description"]
        text = record_to_text(op, timer, desc)
        error_code_id = f"lamp-{op}-{timer.lower()}"
        passages.append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, error_code_id)),
            "text": text,
            "error_code": error_code_id,
        })

    if dry_run:
        print("\n=== DRY RUN — all passages ===\n")
        for p in passages:
            print(f"[{p['error_code']}]  {p['text']}")
        return

    index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(
        os.environ.get("PINECONE_INDEX_NAME", "ai-agent")
    )
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    print(f"Embedding {len(passages)} passages...")
    vectors = await embed_batch(client, [p["text"] for p in passages])

    upsert_records = [
        {
            "id": p["id"],
            "values": vec,
            "metadata": {
                "content": p["text"],
                "error_code": p["error_code"],
                "data_origin": "lamp-blink",
            },
        }
        for p, vec in zip(passages, vectors)
    ]

    print(f"Upserting {len(upsert_records)} vectors into namespace '{NAMESPACE}' (appending)...")
    upsert_batch(index, upsert_records)
    print(f"\nDone. {len(upsert_records)} lamp-blink vectors added to '{NAMESPACE}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest lamp-blink error codes into Pinecone.")
    parser.add_argument("jsonl_path", help="Path to light_error_codes.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Print passages without ingesting")
    args = parser.parse_args()
    asyncio.run(main(args.jsonl_path, args.dry_run))
