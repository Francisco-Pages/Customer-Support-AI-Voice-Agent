"""
Warranty lookup service — scrapes cooperandhunter.us/warranty via Playwright.

The site is a Next.js app backed by a Cloudflare-protected GraphQL API, so
direct HTTP calls are blocked. We use a headless Chromium browser to:
  1. Open the warranty page
  2. Click "VERIFY YOUR WARRANTY" to reveal the MUI dialog
  3. Fill in the serial number and click "FIND"
  4. Parse the [class*=result] element for the response

Runs in a thread executor so it doesn't block the async event loop.
"""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_WARRANTY_URL = "https://cooperandhunter.us/warranty"
_TIMEOUT_MS = 30_000


@dataclass
class WarrantyResult:
    serial_number: str
    found: bool               # False when "serial number not found"
    is_registered: bool
    status_text: str          # Raw result text from the site
    purchase_date: str | None
    installation_date: str | None
    product_title: str | None


def _scrape_warranty_sync(serial_number: str) -> WarrantyResult:
    """
    Synchronous Playwright scrape — run via run_in_executor.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = context.new_page()
            page.goto(_WARRANTY_URL, wait_until="networkidle", timeout=_TIMEOUT_MS)

            # Open the verify dialog
            page.get_by_role("button", name="VERIFY YOUR WARRANTY").click()
            page.wait_for_selector("input[name=serial_number]", timeout=10_000)

            # Submit the serial number
            page.fill("input[name=serial_number]", serial_number.strip())
            page.get_by_role("button", name="FIND").click()

            # Wait for the result element to appear inside the dialog
            page.wait_for_selector("[class*=result]", timeout=_TIMEOUT_MS)

            result_text = (
                page.query_selector("[class*=result]").inner_text() or ""
            ).strip()

            # Determine outcome from result text
            text_lower = result_text.lower()
            not_found = "not found" in text_lower
            found = not not_found
            is_registered = found and any(
                w in text_lower for w in ("registered", "active", "valid", "purchase")
            )

            # Try to extract structured fields from the dialog rows
            purchase_date = None
            installation_date = None
            product_title = None

            dialog = page.query_selector("[class*=MuiDialog]")
            if dialog:
                rows = dialog.query_selector_all("[class*=row], tr, li")
                for row in rows:
                    row_text = (row.inner_text() or "").lower()
                    if "purchase" in row_text:
                        parts = row.inner_text().split(":", 1)
                        if len(parts) == 2:
                            purchase_date = parts[1].strip()
                    elif "install" in row_text:
                        parts = row.inner_text().split(":", 1)
                        if len(parts) == 2:
                            installation_date = parts[1].strip()
                    elif "product" in row_text or "model" in row_text:
                        parts = row.inner_text().split(":", 1)
                        if len(parts) == 2:
                            product_title = parts[1].strip()

            return WarrantyResult(
                serial_number=serial_number,
                found=found,
                is_registered=is_registered,
                status_text=result_text[:600],
                purchase_date=purchase_date,
                installation_date=installation_date,
                product_title=product_title,
            )
        finally:
            browser.close()


async def lookup_warranty(serial_number: str) -> WarrantyResult:
    """Async wrapper — runs the Playwright scrape in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _scrape_warranty_sync, serial_number)
