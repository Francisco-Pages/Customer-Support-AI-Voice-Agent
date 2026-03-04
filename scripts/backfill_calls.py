"""
Backfill ended_at, duration_sec, and resolution for call records that are
missing those fields. Fetches the authoritative data from the Twilio REST API.

Usage:
    python scripts/backfill_calls.py [--dry-run]
"""

import argparse
import asyncio
import logging
import sys
from datetime import timezone
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twilio.rest import Client as TwilioClient
from sqlalchemy import select

from app.config import settings
from app.db.models import Call
from app.dependencies import AsyncSessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"completed", "failed", "busy", "no-answer", "canceled"}


def _resolve_resolution(status: str) -> str:
    return "resolved" if status == "completed" else "abandoned"


async def backfill(dry_run: bool) -> None:
    twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)

    async with AsyncSessionLocal() as db:
        # Fetch all call rows missing at least one of the four fields
        result = await db.execute(
            select(Call).where(
                (Call.ended_at.is_(None))
                | (Call.duration_sec.is_(None))
                | (Call.resolution.is_(None))
                | (Call.caller_phone.is_(None))
            )
        )
        incomplete = result.scalars().all()

    if not incomplete:
        logger.info("No incomplete call records found — nothing to backfill.")
        return

    logger.info("Found %d incomplete call record(s).", len(incomplete))

    updated = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        for call in incomplete:
            try:
                twilio_call = await asyncio.get_event_loop().run_in_executor(
                    None, lambda sid=call.twilio_call_sid: twilio.calls(sid).fetch()
                )
            except Exception as exc:
                logger.warning("Could not fetch SID %s from Twilio: %s", call.twilio_call_sid, exc)
                skipped += 1
                continue

            if twilio_call.status not in _TERMINAL_STATUSES:
                logger.info(
                    "SID %s status=%s — skipping (not terminal).",
                    call.twilio_call_sid,
                    twilio_call.status,
                )
                skipped += 1
                continue

            duration = int(twilio_call.duration or 0)
            ended_at = (
                twilio_call.end_time.replace(tzinfo=timezone.utc)
                if twilio_call.end_time
                else None
            )
            resolution = call.resolution or _resolve_resolution(twilio_call.status)

            caller_phone = twilio_call._from

            logger.info(
                "%sSID %s | status=%s duration=%ss ended_at=%s resolution=%s caller_phone=%s",
                "[DRY RUN] " if dry_run else "",
                call.twilio_call_sid,
                twilio_call.status,
                duration,
                ended_at,
                resolution,
                caller_phone,
            )

            if not dry_run:
                # Re-fetch within this session to get a managed instance
                row = (
                    await db.execute(select(Call).where(Call.id == call.id))
                ).scalar_one()
                if row.ended_at is None:
                    row.ended_at = ended_at
                if row.duration_sec is None:
                    row.duration_sec = duration
                if row.resolution is None:
                    row.resolution = resolution
                if row.caller_phone is None:
                    row.caller_phone = caller_phone

            updated += 1

        if not dry_run:
            await db.commit()
            logger.info("Committed. Updated %d record(s), skipped %d.", updated, skipped)
        else:
            logger.info("[DRY RUN] Would update %d record(s), skip %d.", updated, skipped)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill call records from Twilio.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be updated without writing to the database.",
    )
    args = parser.parse_args()
    asyncio.run(backfill(args.dry_run))
