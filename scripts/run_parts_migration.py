"""
Create the parts and part_compatibility tables (and required indexes).

Usage:
    python scripts/run_parts_migration.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from app.dependencies import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS parts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    part_type    VARCHAR(100) NOT NULL,
    part_name    VARCHAR(200) NOT NULL,
    part_number  VARCHAR(100) NOT NULL,
    brand        VARCHAR(100) NOT NULL,
    CONSTRAINT parts_part_number_key UNIQUE (part_number)
);

CREATE INDEX IF NOT EXISTS ix_parts_brand_part_type
    ON parts (brand, part_type);

CREATE TABLE IF NOT EXISTS part_compatibility (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    part_id       UUID NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    product_model VARCHAR(150) NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_part_compatibility_product_model
    ON part_compatibility (product_model);

CREATE INDEX IF NOT EXISTS ix_part_compatibility_product_model_trgm
    ON part_compatibility USING GIN (product_model gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_part_compatibility_part_id
    ON part_compatibility (part_id);
"""


async def main() -> None:
    async with AsyncSessionLocal() as db:
        for statement in SQL.strip().split(";"):
            statement = statement.strip()
            if statement:
                await db.execute(text(statement))
                log.info(f"  OK: {statement.splitlines()[0]}")
        await db.commit()
    log.info("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
