-- Parts catalog tables for HVAC parts lookup.
--
-- Run once against your database:
--   psql $DATABASE_URL -f scripts/create_parts_tables.sql

-- Required for similarity() and GIN trigram indexes.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- parts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS parts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    part_type    VARCHAR(100) NOT NULL,
    part_name    VARCHAR(200) NOT NULL,
    part_number  VARCHAR(100) NOT NULL,
    brand        VARCHAR(100) NOT NULL,
    CONSTRAINT parts_part_number_key UNIQUE (part_number)
);

-- Filters by brand + part type before joining part_compatibility.
CREATE INDEX IF NOT EXISTS ix_parts_brand_part_type
    ON parts (brand, part_type);

-- ---------------------------------------------------------------------------
-- part_compatibility
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS part_compatibility (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    part_id       UUID NOT NULL REFERENCES parts (id) ON DELETE CASCADE,
    product_model VARCHAR(150) NOT NULL
);

-- B-tree for exact lookups.
CREATE INDEX IF NOT EXISTS ix_part_compatibility_product_model
    ON part_compatibility (product_model);

-- GIN trigram index for fuzzy matching (customers omit dashes, etc.).
CREATE INDEX IF NOT EXISTS ix_part_compatibility_product_model_trgm
    ON part_compatibility USING GIN (product_model gin_trgm_ops);

-- FK index so cascading deletes and joins on part_id are fast.
CREATE INDEX IF NOT EXISTS ix_part_compatibility_part_id
    ON part_compatibility (part_id);
