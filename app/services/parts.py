"""
Parts service — look up part numbers by brand, part type/name, and product model.
"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Part, PartCompatibility


async def lookup_parts(
    db: AsyncSession,
    product_model: str,
    brand: str | None = None,
    part_type: str | None = None,
    part_name: str | None = None,
    similarity_threshold: float = 0.25,
    limit: int = 5,
) -> list[dict]:
    """
    Find parts compatible with a given product model.

    Matches product_model using pg_trgm similarity so minor variations
    (missing dashes, extra spaces) still resolve correctly.

    At least one of brand, part_type, or part_name should be provided to
    narrow results; product_model alone will search across all part types.

    Returns a list of dicts with keys: part_number, part_name, part_type,
    brand, matched_model, similarity.
    """
    similarity_expr = func.similarity(PartCompatibility.product_model, product_model)

    stmt = (
        select(
            Part.part_number,
            Part.part_name,
            Part.part_type,
            Part.brand,
            PartCompatibility.product_model.label("matched_model"),
            similarity_expr.label("similarity"),
        )
        .join(PartCompatibility, PartCompatibility.part_id == Part.id)
        .where(similarity_expr >= similarity_threshold)
        .order_by(similarity_expr.desc())
        .limit(limit)
    )

    if brand:
        stmt = stmt.where(Part.brand.ilike(f"%{brand}%"))
    if part_type:
        stmt = stmt.where(Part.part_type.ilike(f"%{part_type}%"))
    if part_name:
        stmt = stmt.where(Part.part_name.ilike(f"%{part_name}%"))

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "part_number": r.part_number,
            "part_name": r.part_name,
            "part_type": r.part_type,
            "brand": r.brand,
            "matched_model": r.matched_model,
            "similarity": round(r.similarity, 2),
        }
        for r in rows
    ]
