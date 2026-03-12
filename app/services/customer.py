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


async def update(
    db: AsyncSession,
    customer_id: uuid.UUID,
    name: str | None = None,
    email: str | None = None,
    caller_type: str | None = None,
) -> Customer | None:
    """Update a customer's name, email, and/or caller_type. Skips None fields."""
    customer = await get_by_id(db, customer_id)
    if not customer:
        return None
    if name is not None:
        customer.name = name
    if email is not None:
        customer.email = email
    if caller_type is not None:
        customer.caller_type = caller_type
    await db.flush()
    return customer


async def list_customers(
    db: AsyncSession,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Customer]]:
    """Return (total, customers) with optional name/phone/email search."""
    from sqlalchemy import func as sa_func, or_

    base_q = select(Customer)
    if search:
        like = f"%{search}%"
        base_q = base_q.where(
            or_(
                Customer.phone.ilike(like),
                Customer.name.ilike(like),
                Customer.email.ilike(like),
            )
        )

    total_result = await db.execute(select(sa_func.count()).select_from(base_q.subquery()))
    total = total_result.scalar_one()

    result = await db.execute(
        base_q.order_by(Customer.created_at.desc()).limit(limit).offset(offset)
    )
    return total, list(result.scalars().all())


async def create(
    db: AsyncSession,
    phone: str,
    name: str | None = None,
    email: str | None = None,
    address: str | None = None,
    caller_type: str | None = None,
    tcpa_consent: bool = False,
) -> Customer:
    customer = Customer(
        phone=phone,
        name=name,
        email=email,
        address=address,
        caller_type=caller_type,
        tcpa_consent=tcpa_consent,
    )
    db.add(customer)
    await db.flush()
    return customer


async def delete(db: AsyncSession, customer_id: uuid.UUID) -> bool:
    """Delete a customer by ID. Returns True if deleted, False if not found."""
    customer = await get_by_id(db, customer_id)
    if not customer:
        return False
    await db.delete(customer)
    await db.flush()
    return True


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
