"""
Customer service — CRUD operations on the customers table.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Customer


async def get_by_phone(db: AsyncSession, phone: str) -> Customer | None:
    result = await db.execute(select(Customer).where(Customer.phone == phone))
    return result.scalar_one_or_none()


async def get_by_phone_with_products(db: AsyncSession, phone: str) -> Customer | None:
    """Load the customer and their registered products in a single query."""
    result = await db.execute(
        select(Customer)
        .where(Customer.phone == phone)
        .options(selectinload(Customer.products))
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, customer_id: uuid.UUID) -> Customer | None:
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    return result.scalar_one_or_none()


async def get_or_create(db: AsyncSession, phone: str) -> tuple[Customer, bool]:
    """
    Return (customer, was_created).

    If no record exists for this phone number, create one and flush it so
    the generated UUID is available immediately. The caller's transaction
    (via the get_db dependency) commits when the request finishes.
    """
    customer = await get_by_phone(db, phone)
    if customer:
        return customer, False

    customer = Customer(phone=phone)
    db.add(customer)
    await db.flush()
    return customer, True
