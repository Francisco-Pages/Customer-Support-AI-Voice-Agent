"""
Re-ingest unit specs from all_unit_specs.jsonl into the unit-specs Pinecone namespace.

The original data was stored as raw key-value metadata with no `content` field,
making it unsearchable by the RAG retriever. This script converts each record
into a natural-language text passage and re-upserts it.

Usage:
    python scripts/reingest_unit_specs.py ~/Downloads/all_unit_specs_normalized.jsonl

Options:
    --dry-run   Print converted passages without touching Pinecone
    --no-delete Skip deleting old vectors (useful if you just want to add new ones)
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from openai import AsyncOpenAI
from pinecone import Pinecone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NAMESPACE = "unit-specs"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
EMBED_BATCH_SIZE = 100
UPSERT_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Text conversion
# ---------------------------------------------------------------------------

def _build_lookup(d: dict) -> dict:
    """Return a case-insensitive lookup dict (lowercase keys → original value)."""
    return {k.lower(): v for k, v in d.items()}


def _v(lookup: dict, *keys) -> str:
    """
    Return first non-empty value matching any of the given keys (case-insensitive).
    Pass the result of _build_lookup(e), not e directly.
    """
    for k in keys:
        v = str(lookup.get(k.lower(), "") or "").strip()
        if v:
            return v
    return ""


def spec_to_text(e: dict) -> str:
    """
    Convert a spec embedding dict to a natural-language passage for embedding.
    Uses case-insensitive key matching to handle the inconsistent column naming
    across different CSV exports that were merged into this dataset.
    Only includes fields with values; skips blank/null entries.
    """
    lk = _build_lookup(e)  # case-insensitive lookup
    lines = []

    # --- Identity (primary identifiers first) ---
    identity_parts = [
        f"Brand: {_v(lk, 'brand')}",
        f"Model: {_v(lk, 'model_number', 'model number')}",
        f"Unit Type: {_v(lk, 'unit type')}",
        f"Refrigerant: {_v(lk, 'refrigerant type')}",
    ]
    if _v(lk, 'model name'):
        identity_parts.append(f"Name: {_v(lk, 'model name')}")
    if _v(lk, 'series'):
        identity_parts.append(f"Series: {_v(lk, 'series')}")
    if _v(lk, 'type', 'ducted or non-ducted'):
        identity_parts.append(f"Ducting: {_v(lk, 'type', 'ducted or non-ducted')}")
    if _v(lk, 'system type'):
        identity_parts.append(f"System: {_v(lk, 'system type')}")
    if _v(lk, 'max quantity of zones'):
        identity_parts.append(f"Max zones: {_v(lk, 'max quantity of zones')}")
    if _v(lk, 'description', 'unit description', 'indoor unit description'):
        identity_parts.append(f"Description: {_v(lk, 'description', 'unit description', 'indoor unit description')}")
    lines.append(" | ".join(identity_parts))

    # --- Compatibility ---
    compat_parts = []
    if _v(lk, 'matching outdoor model number', 'matching outdoor model', 'outdoor model'):
        compat_parts.append(f"Matching outdoor unit: {_v(lk, 'matching outdoor model number', 'matching outdoor model', 'outdoor model')}")
    if _v(lk, 'system model numbers (outdoor/indoor)'):
        compat_parts.append(f"System model numbers: {_v(lk, 'system model numbers (outdoor/indoor)')}")
    if _v(lk, 'controller'):
        compat_parts.append(f"Controller: {_v(lk, 'controller')}")
    if compat_parts:
        lines.append("Compatibility — " + " | ".join(compat_parts))

    # --- Certifications ---
    cert_parts = []
    if _v(lk, 'energy star certification'):
        cert_parts.append("Energy Star")
    if _v(lk, 'ahri certification'):
        cert_parts.append(f"AHRI: {_v(lk, 'ahri certification')}")
    if _v(lk, 'etl certification'):
        cert_parts.append("ETL")
    if _v(lk, 'neep certification'):
        cert_parts.append("NEEP")
    if _v(lk, 'ul certification'):
        cert_parts.append("UL")
    if cert_parts:
        lines.append("Certifications — " + " | ".join(cert_parts))

    # --- Electrical ---
    elec_parts = []
    if _v(lk, 'power source (v, ph, hz)', 'rated power supply (v, ph, hz)', 'power source (v, hz, ph)'):
        elec_parts.append(f"Power: {_v(lk, 'power source (v, ph, hz)', 'rated power supply (v, ph, hz)', 'power source (v, hz, ph)')}")
    if _v(lk, 'voltage range (v)', 'rated voltage range (v)'):
        elec_parts.append(f"Voltage range: {_v(lk, 'voltage range (v)', 'rated voltage range (v)')}V")
    if _v(lk, 'minimum circuit ampacity (a)', 'min. circuit ampacity (mca) (a)'):
        elec_parts.append(f"Min circuit ampacity: {_v(lk, 'minimum circuit ampacity (a)', 'min. circuit ampacity (mca) (a)')}A")
    if _v(lk, 'maximum fuse size (a)', 'max. fuse (a)', 'max.fuse (outdoor unit) (a)', 'max. fuse size (a)'):
        elec_parts.append(f"Max fuse: {_v(lk, 'maximum fuse size (a)', 'max. fuse (a)', 'max.fuse (outdoor unit) (a)', 'max. fuse size (a)')}A")
    if elec_parts:
        lines.append(" | ".join(elec_parts))

    # --- Cooling ---
    cool_parts = []
    rated_cool = _v(lk, 'cooling capacity (nominal) (btu/h)', 'rated cooling capacity (btu/h)',
                    'rated cooling capacity range (btu/h)', 'cooling capacity (btu/h)', 'btu/h', 'btu rated (btu/h)')
    if rated_cool:
        cool_parts.append(f"Rated cooling: {rated_cool} BTU/h")
    if _v(lk, 'cooling capacity range (btu/h) at 95 f', 'cooling capacity (btu/h) min/max at 95 f',
           'capacity (range) cooling at 95f (btu/h)', 'cooling capacity (min/max) (btu/h)'):
        cool_parts.append(f"Range at 95°F: {_v(lk, 'cooling capacity range (btu/h) at 95 f', 'cooling capacity (btu/h) min/max at 95 f', 'capacity (range) cooling at 95f (btu/h)', 'cooling capacity (min/max) (btu/h)')}")
    seer2 = _v(lk, 'cooling at 95f seer2', 'cooling seer2 (btu/h)', 'cooling seer2 (btu/w)',
               'seer up to', 'cooling at 95f seer2 ', 'cooling seer')
    if seer2:
        cool_parts.append(f"SEER2: {seer2}")
    eer2 = _v(lk, 'cooling at 95f eer2', 'cooling eer2 (btu/h)', 'cooling eer2 (btu/w)',
              'eer up to btu/w', 'eer up to', 'eer up to (btu/w)', 'eer2 up to', 'eer2 cooling at 95f',
              'cooling eer (btu/w)', 'eer (w/w)')
    if eer2:
        cool_parts.append(f"EER2: {eer2}")
    if _v(lk, 'cooling input (w) at 95f', 'cooling input (w)'):
        cool_parts.append(f"Input: {_v(lk, 'cooling input (w) at 95f', 'cooling input (w)')}W")
    if _v(lk, 'cooling rated current (a) at 95f', 'cooling rated current (a)', 'rated cooling current (a)'):
        cool_parts.append(f"Current: {_v(lk, 'cooling rated current (a) at 95f', 'cooling rated current (a)', 'rated cooling current (a)')}A")
    if _v(lk, 'dehumidification (pnt/h)', 'dehumidification (pnt/h)'):
        cool_parts.append(f"Dehumidification: {_v(lk, 'dehumidification (pnt/h)')} pt/h")
    if cool_parts:
        lines.append("Cooling — " + " | ".join(cool_parts))

    # --- Heating ---
    heat_parts = []
    rated_heat = _v(lk, 'heating capacity (nominal) (btu/h)', 'heating capacity (nominal) (btu/h)',
                    'rated heating capacity (btu/h)', 'heating capacity range (btu/h) at 47f',
                    'heating capacity min/max (btu/w) at 47f', 'heating capacity (min/max) (btu/h)',
                    'heating capacity (nominal) (btu/h)')
    if rated_heat:
        heat_parts.append(f"Rated heating: {rated_heat} BTU/h")
    cop = _v(lk, 'heating at 47f cop', 'heating at 47f cop (w/w)', 'cop w/w', 'cop (w/w)',
             'cop heating at 47f (w/w)', 'heating cop (w/w)', 'heating cop at 47f (w/w)')
    if cop:
        heat_parts.append(f"COP at 47°F: {cop}")
    hspf4 = _v(lk, 'heating at 47f hspf2-4', 'hspf2-4', 'heating at 47f (hspf4)',
               'heating at 47f (hspf4) (btu/w)', 'hspf4 heating at 47f', 'heating hspf4 at 47f')
    if hspf4:
        heat_parts.append(f"HSPF2-4: {hspf4}")
    hspf5 = _v(lk, 'heating at 47f hspf2-5', 'hspf2-5', 'heating at 47f (hspf5)',
               'heating at 47f (hspf5) (btu/h)', 'heating at 47f (hspf5) (btu/w)',
               'hspf5 heating at 47f', 'heating hspf5 at 47f')
    if hspf5:
        heat_parts.append(f"HSPF2-5: {hspf5}")
    if _v(lk, 'heating at 5f (-15c) rated capacity (btu/h)', 'heating at 5f (-15c) rated capacity (btu/h)',
           'heating at 5f rated capacity range (btu/h)', 'heating at 17f (ahri) rated capacity (btu/h)',
           'heating at 17f rated capacity'):
        heat_parts.append(f"Capacity at 5°F: {_v(lk, 'heating at 5f (-15c) rated capacity (btu/h)', 'heating at 5f (-15c) rated capacity (btu/h)', 'heating at 5f rated capacity range (btu/h)', 'heating at 17f (ahri) rated capacity (btu/h)', 'heating at 17f rated capacity')} BTU/h")
    if _v(lk, 'heating input (w) at 47f', 'heating input (w)'):
        heat_parts.append(f"Input: {_v(lk, 'heating input (w) at 47f', 'heating input (w)')}W")
    if _v(lk, 'heating rated current (a) at 47f', 'heating rated current (a)', 'rated heating current (a)',
           'heating rated current (a) at 47f'):
        heat_parts.append(f"Current: {_v(lk, 'heating rated current (a) at 47f', 'heating rated current (a)', 'rated heating current (a)')}A")
    if heat_parts:
        lines.append("Heating — " + " | ".join(heat_parts))

    # --- Refrigerant ---
    ref_parts = []
    if _v(lk, 'refrigerant type', 'refrigerant type (g)', 'refrigerant type (oz)'):
        ref_parts.append(f"Type: {_v(lk, 'refrigerant type', 'refrigerant type (g)', 'refrigerant type (oz)')}")
    if _v(lk, 'refrigerant charge (oz)', 'refrigerant type / charge (oz.)'):
        ref_parts.append(f"Charge: {_v(lk, 'refrigerant charge (oz)', 'refrigerant type / charge (oz.)')} oz")
    if _v(lk, 'refrigerant precharge (ft)', 'refrigerant precharge length (ft.)'):
        ref_parts.append(f"Pre-charge: {_v(lk, 'refrigerant precharge (ft)', 'refrigerant precharge length (ft.)')} ft")
    if ref_parts:
        lines.append("Refrigerant — " + " | ".join(ref_parts))

    # --- Piping ---
    pipe_parts = []
    pipe_sizes = _v(lk, 'refrigerant piping liquid/gas side (inch)',
                    'refrigerant piping liquid side/gas side (inch)',
                    'liquid side/gas side (inch)',
                    'refrigerant piping liquid side/gas side (inch)',
                    'diameter of refrigerant pipe liquid/gas side (inch)',
                    'refrigerant piping liquid side/gas side (mm(inch))')
    if pipe_sizes:
        pipe_parts.append(f"Pipe sizes (liquid/gas): {pipe_sizes}")
    max_total = _v(lk, 'refrigerant piping max length for all rooms (ft)',
                   'max pipe length (ft)', 'max. pipe length (ft.)',
                   'refrigerant piping max. pipe length (ft.)',
                   'max refrigerant pipe length (ft)',
                   'max. refrigerant piping length for all rooms (ft)',
                   'max. pipe length for one indoor unit (ft.)')
    if max_total:
        pipe_parts.append(f"Max total pipe length: {max_total} ft")
    max_per = _v(lk, 'refrigerant piping max length for one indoor unit (ft)',
                 'max. refrigerant piping length for one indoor unit (ft)')
    if max_per:
        pipe_parts.append(f"Max per unit: {max_per} ft")
    max_hd = _v(lk, 'refrigerant piping max height difference between indoor and outdoor',
                'max. difference in level (ft.)', 'max. height difference in level (ft.)',
                'max refrigerant pipe difference in level (ft)',
                'max. refrigerant piping height elevation between indoor and outdoor (ft)')
    if max_hd:
        pipe_parts.append(f"Max height diff (indoor/outdoor): {max_hd} ft")
    max_hd2 = _v(lk, 'refrigerant piping max height difference between indoor units (ft)',
                 'max. refrigerant piping height elevation between indoor units (ft)')
    if max_hd2:
        pipe_parts.append(f"Max height diff between indoor units: {max_hd2} ft")
    add_14 = _v(lk, 'additional charge for 1/4 inch liquid pipe (oz)',
                'additional charge for each ft. (oz/ft)', 'additional charge for each ft (oz)')
    if add_14:
        pipe_parts.append(f"Add. charge 1/4\" pipe: {add_14} oz/ft")
    add_34 = _v(lk, 'additional charge for 3/4 inch liquid pipe (oz)',
                'additional charge for 3/8 inch liquid pipe (oz)')
    if add_34:
        pipe_parts.append(f"Add. charge 3/8\"-3/4\" pipe: {add_34} oz/ft")
    if pipe_parts:
        lines.append("Piping — " + " | ".join(pipe_parts))

    # --- Operating range ---
    op_parts = []
    cool_amb = _v(lk, 'ambient temperature cooling (f)', 'ambient temperature cooling (f)',
                  'ambient temperature - cooling (f)', 'operating room temperature cooling (f)',
                  'room temperature cooling (f)', 'indoor operating temperature cooling/heating (f)')
    if cool_amb:
        op_parts.append(f"Cooling ambient: {cool_amb}°F")
    heat_amb = _v(lk, 'ambient temperature (heating (f)', 'ambient temperature heating (f)',
                  'ambient temperature - heating (f)', 'operating room temperature heating (f)',
                  'room temperature heating (f)')
    if heat_amb:
        op_parts.append(f"Heating ambient: {heat_amb}°F")
    if op_parts:
        lines.append("Operating range — " + " | ".join(op_parts))

    # --- Noise ---
    noise_parts = []
    outdoor_noise = _v(lk, 'noise level (db)', 'outdoor noise level (sound pressure) (db(a))',
                       'outdoor noise level (db)', 'outdoor noise level (dba)')
    if outdoor_noise:
        noise_parts.append(f"Outdoor: {outdoor_noise} dB")
    indoor_noise = _v(lk, 'indoor noise level hi/mi/lo (db)', 'indoor noise level (turbo/hi/mi/lo/si) (db(a))',
                      'noise level hi/mi/lo (db)', 'indoor noise level (hi/lo) (db)',
                      'indoor noise level (hi/med/lo) (db)', 'indoor noise level (hi/med/lo) (dba)',
                      'airflow turbo/hi/mi/lo (cfm)')
    if indoor_noise:
        noise_parts.append(f"Indoor (hi/mi/lo): {indoor_noise} dB")
    if noise_parts:
        lines.append("Noise — " + " | ".join(noise_parts))

    # --- Physical ---
    phys_parts = []
    dims = _v(lk, 'dimensions wxdxh (inch)', 'product dimensions (wxdxh) inches',
              'product dimension (wxdxh) (inch)', 'unit dimensions wxdxh (inch)',
              'unit dimensions (wxdxh) (inch)')
    if dims:
        phys_parts.append(f"Dimensions (WxDxH): {dims} in")
    weight = _v(lk, 'net/gross weight (lbs)', 'net/gross weight (lbs.)', 'net/gross weight (lb)',
                'net/gross weight', 'net/gross weight (lbs.)')
    if weight:
        phys_parts.append(f"Weight (net/gross): {weight} lbs")
    if phys_parts:
        lines.append("Physical — " + " | ".join(phys_parts))

    # --- Compressor ---
    comp_parts = []
    if _v(lk, 'compressor type'):
        comp_parts.append(f"Type: {_v(lk, 'compressor type')}")
    if _v(lk, 'compressor brand'):
        comp_parts.append(f"Brand: {_v(lk, 'compressor brand')}")
    if _v(lk, 'compressor capacity (btu/h)'):
        comp_parts.append(f"Capacity: {_v(lk, 'compressor capacity (btu/h)')} BTU/h")
    if comp_parts:
        lines.append("Compressor — " + " | ".join(comp_parts))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pinecone + OpenAI helpers
# ---------------------------------------------------------------------------

def get_index():
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return pc.Index(os.environ.get("PINECONE_INDEX_NAME", "ai-agent"))


def delete_namespace(index):
    print(f"Deleting all vectors in namespace '{NAMESPACE}'...")
    index.delete(delete_all=True, namespace=NAMESPACE)
    time.sleep(2)  # Give Pinecone a moment to process
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(jsonl_path: str, dry_run: bool, no_delete: bool):
    # Load records
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"Loaded {len(records)} records from {jsonl_path}")

    # Convert to text passages
    passages = []
    for r in records:
        e = r["metadata"]["embedding"]
        lk = _build_lookup(e)
        text = spec_to_text(e)
        passages.append({
            "original_id": r["id"],
            "text": text,
            "brand": _v(lk, "brand"),
            "model_number": _v(lk, "model_number", "model number"),
            "unit_type": _v(lk, "unit type"),
            "refrigerant_type": _v(lk, "refrigerant type"),
        })

    if dry_run:
        print("\n=== DRY RUN — showing first 3 passages ===\n")
        for p in passages[:3]:
            print(f"--- {p['brand']} | {p['model_number']} | {p['unit_type']} | {p['refrigerant_type']} ---")
            print(p["text"])
            print()
        return

    # Connect
    index = get_index()
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # Delete old vectors
    if not no_delete:
        delete_namespace(index)

    # Embed all passages
    print(f"Embedding {len(passages)} passages...")
    texts = [p["text"] for p in passages]
    vectors = await embed_batch(client, texts)

    # Build upsert records — reuse original UUID as the vector ID
    upsert_records = [
        {
            "id": p["original_id"],
            "values": vec,
            "metadata": {
                "content": p["text"],
                "brand": p["brand"],
                "model_number": p["model_number"],
                "unit_type": p["unit_type"],
                "refrigerant_type": p["refrigerant_type"],
            },
        }
        for p, vec in zip(passages, vectors)
    ]

    print(f"Upserting {len(upsert_records)} vectors into namespace '{NAMESPACE}'...")
    upsert_batch(index, upsert_records)

    print(f"\nDone. {len(upsert_records)} vectors upserted into '{NAMESPACE}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-ingest unit specs into Pinecone.")
    parser.add_argument("jsonl_path", help="Path to all_unit_specs.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Print passages without ingesting")
    parser.add_argument("--no-delete", action="store_true", help="Skip deleting existing vectors")
    args = parser.parse_args()

    asyncio.run(main(args.jsonl_path, args.dry_run, args.no_delete))
