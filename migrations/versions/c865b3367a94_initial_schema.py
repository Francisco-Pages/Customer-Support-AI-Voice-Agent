"""initial schema

Revision ID: c865b3367a94
Revises:
Create Date: 2026-02-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "c865b3367a94"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # customers
    # ------------------------------------------------------------------
    op.create_table(
        "customers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("email", sa.String(200)),
        sa.Column("address", sa.Text),
        sa.Column("tcpa_consent", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_customers_phone", "customers", ["phone"], unique=True)

    # ------------------------------------------------------------------
    # customer_products
    # ------------------------------------------------------------------
    op.create_table(
        "customer_products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("product_model", sa.String(100), nullable=False),
        sa.Column("product_line", sa.String(50), nullable=False),
        sa.Column("serial_number", sa.String(100)),
        sa.Column("purchase_date", sa.DateTime(timezone=True)),
        sa.Column("warranty_end_date", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_customer_products_customer_id", "customer_products", ["customer_id"]
    )

    # ------------------------------------------------------------------
    # calls
    # ------------------------------------------------------------------
    op.create_table(
        "calls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", UUID(as_uuid=True)),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("twilio_call_sid", sa.String(50), nullable=False),
        sa.Column("livekit_room", sa.String(200)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("duration_sec", sa.Integer),
        sa.Column("transcript", sa.Text),
        sa.Column("summary", sa.Text),
        sa.Column("resolution", sa.String(50)),
        sa.Column(
            "safety_event", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_calls_twilio_call_sid", "calls", ["twilio_call_sid"], unique=True)
    op.create_index("ix_calls_customer_id", "calls", ["customer_id"])

    # ------------------------------------------------------------------
    # appointments
    # ------------------------------------------------------------------
    op.create_table(
        "appointments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", UUID(as_uuid=True)),
        sa.Column("appointment_type", sa.String(50), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="scheduled"
        ),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_appointments_customer_id", "appointments", ["customer_id"]
    )

    # ------------------------------------------------------------------
    # outbound_queue
    # ------------------------------------------------------------------
    op.create_table(
        "outbound_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_type", sa.String(50), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending"
        ),
        sa.Column("twilio_call_sid", sa.String(50)),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_outbound_queue_customer_id", "outbound_queue", ["customer_id"]
    )
    op.create_index("ix_outbound_queue_status", "outbound_queue", ["status"])


def downgrade() -> None:
    op.drop_table("outbound_queue")
    op.drop_table("appointments")
    op.drop_table("calls")
    op.drop_table("customer_products")
    op.drop_table("customers")
