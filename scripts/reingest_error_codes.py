"""
Re-ingest error codes from error_codes.jsonl into the error-codes Pinecone namespace.

The original data stored the error code in `metadata.embedding` (a string) and the
description in `metadata["Error Description"]`, leaving `content` empty. This script
builds a natural-language passage and re-upserts all vectors.

Usage:
    python scripts/reingest_error_codes.py ~/Downloads/error_codes.jsonl

Options:
    --dry-run   Print converted passages without touching Pinecone
    --no-delete Skip deleting old vectors
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from openai import AsyncOpenAI
from pinecone import Pinecone

NAMESPACE = "error-codes"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
EMBED_BATCH_SIZE = 100
UPSERT_BATCH_SIZE = 100


def record_to_text(error_code: str, description: str) -> str:
    return f"Error Code: {error_code} — {description}"


def get_index():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return pc.Index(os.environ.get("PINECONE_INDEX_NAME", "ai-agent"))


def delete_namespace(index):
    print(f"Deleting all vectors in namespace '{NAMESPACE}'...")
    index.delete(delete_all=True, namespace=NAMESPACE)
    time.sleep(2)
    print("  Done.")


async def embed_batch(client: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
    all_vectors = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        response = await client.embeddings.create(
            input=batch,
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        all_vectors.extend([item.embedding for item in response.data])
        print(f"  Embedded {min(i + EMBED_BATCH_SIZE, len(texts))}/{len(texts)}", end="\r")
    print()
    return all_vectors


def upsert_batch(index, records: list[dict]):
    for i in range(0, len(records), UPSERT_BATCH_SIZE):
        batch = records[i : i + UPSERT_BATCH_SIZE]
        index.upsert(vectors=batch, namespace=NAMESPACE)
        print(f"  Upserted {min(i + UPSERT_BATCH_SIZE, len(records))}/{len(records)}", end="\r")
    print()


async def main(jsonl_path: str, dry_run: bool, no_delete: bool):
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"Loaded {len(records)} records from {jsonl_path}")

    passages = []
    for r in records:
        error_code = r["metadata"]["embedding"]
        description = r["metadata"].get("Error Description", "")
        text = record_to_text(error_code, description)
        passages.append({
            "original_id": r["id"],
            "text": text,
            "error_code": error_code,
        })

    if dry_run:
        print("\n=== DRY RUN — showing first 5 passages ===\n")
        for p in passages[:5]:
            print(f"[{p['error_code']}] {p['text']}")
        return

    index = get_index()
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    if not no_delete:
        delete_namespace(index)

    print(f"Embedding {len(passages)} passages...")
    texts = [p["text"] for p in passages]
    vectors = await embed_batch(client, texts)

    upsert_records = [
        {
            "id": p["original_id"],
            "values": vec,
            "metadata": {
                "content": p["text"],
                "error_code": p["error_code"],
            },
        }
        for p, vec in zip(passages, vectors)
    ]

    print(f"Upserting {len(upsert_records)} vectors into namespace '{NAMESPACE}'...")
    upsert_batch(index, upsert_records)

    print(f"\nDone. {len(upsert_records)} vectors upserted into '{NAMESPACE}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-ingest error codes into Pinecone.")
    parser.add_argument("jsonl_path", help="Path to error_codes.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Print passages without ingesting")
    parser.add_argument("--no-delete", action="store_true", help="Skip deleting existing vectors")
    args = parser.parse_args()

    asyncio.run(main(args.jsonl_path, args.dry_run, args.no_delete))
