"""
Import a parts CSV into the parts + part_compatibility tables.

Expected CSV columns (in any order):
    Part Type, Part Name, Part Number, Brand, Product Model Number

Safe to re-run — parts are upserted by part_number, and compatibility rows
are only inserted if they don't already exist.

Usage:
    python scripts/import_parts_csv.py path/to/parts.csv [path/to/more.csv ...]

Example:
    python scripts/import_parts_csv.py "downloads/Fan Motors.csv" "downloads/Capacitors.csv"
"""

import asyncio
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.dependencies import AsyncSessionLocal
from app.db.models import Part, PartCompatibility

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"Part Type", "Part Name", "Part Number", "Brand", "Product Model Number"}


async def import_csv(path: Path) -> None:
    log.info(f"Importing {path.name} ...")

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not REQUIRED_COLUMNS.issubset(set(reader.fieldnames or [])):
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            raise ValueError(f"{path.name}: missing columns: {missing}")
        rows = list(reader)

    if not rows:
        log.info(f"  {path.name}: no data rows, skipping.")
        return

    # Group rows by part_number so we insert each part once.
    parts: dict[str, dict] = {}
    compat: dict[str, list[str]] = {}  # part_number → [product_models]

    for row in rows:
        pn = (row.get("Part Number") or "").strip()
        model = (row.get("Product Model Number") or "").strip()
        if not pn or not model:
            continue
        if pn not in parts:
            parts[pn] = {
                "part_type": row["Part Type"].strip(),
                "part_name": row["Part Name"].strip(),
                "part_number": pn,
                "brand": row["Brand"].strip(),
            }
            compat[pn] = []
        compat[pn].append(model)

    async with AsyncSessionLocal() as db:
        inserted_parts = 0
        inserted_compat = 0

        for pn, part_data in parts.items():
            # Upsert the part row — update name/type if it changed.
            stmt = (
                pg_insert(Part)
                .values(**part_data)
                .on_conflict_do_update(
                    index_elements=["part_number"],
                    set_={
                        "part_type": part_data["part_type"],
                        "part_name": part_data["part_name"],
                        "brand": part_data["brand"],
                    },
                )
                .returning(Part.id)
            )
            result = await db.execute(stmt)
            part_id = result.scalar_one()

            # Fetch existing compatible models for this part to avoid duplicates.
            existing_result = await db.execute(
                select(PartCompatibility.product_model).where(
                    PartCompatibility.part_id == part_id
                )
            )
            existing_models = {r[0] for r in existing_result.all()}

            new_models = [m for m in compat[pn] if m not in existing_models]
            if new_models:
                db.add_all(
                    [PartCompatibility(part_id=part_id, product_model=m) for m in new_models]
                )
                inserted_compat += len(new_models)

            inserted_parts += 1

        await db.commit()

    log.info(
        f"  Done — {inserted_parts} parts upserted, "
        f"{inserted_compat} compatibility rows inserted."
    )


async def main(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            log.error(f"File not found: {path}")
            sys.exit(1)
        await import_csv(path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main([Path(p) for p in sys.argv[1:]]))
