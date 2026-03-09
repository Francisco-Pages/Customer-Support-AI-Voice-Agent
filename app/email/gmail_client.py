"""
Gmail SMTP client for sending product document emails.

Uses smtplib.SMTP_SSL with a Gmail App Password (no OAuth).
All blocking SMTP calls are wrapped in asyncio.run_in_executor so they
do not block the async event loop.
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.documents.catalog import get_catalog_html, get_product_html

logger = logging.getLogger(__name__)

_EMAIL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en" style="margin:0; padding:0;">
<head>
  <meta charset="UTF-8" />
  <title>{model_name} Product Documents</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    @media only screen and (max-width: 600px) {{
      .container {{ width: 100% !important; }}
      .mobile-full {{ width: 100% !important; display: block !important; }}
      .center-text {{ text-align: center !important; }}
    }}
  </style>
</head>
<body style="margin:0; padding:0; background-color:#f4f4f4;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" bgcolor="#f4f4f4">
    <tr>
      <td align="center" style="padding:20px 10px;">
        <table class="container" width="600" border="0" cellspacing="0" cellpadding="0"
               style="max-width:600px; width:100%; background-color:#ffffff; border-radius:4px; overflow:hidden;">
          <tr>
            <td align="center"
                style="padding:20px; background-color:#111827; color:#ffffff; font-family:Arial, sans-serif; font-size:24px; font-weight:bold;">
              Comfortside
            </td>
          </tr>
          <tr>
            <td style="padding:24px 24px 8px 24px; font-family:Arial, sans-serif; color:#111827;">
              <h1 style="margin:0 0 12px 0; font-size:22px; line-height:1.4; font-weight:bold;">
                Thank you for contacting us.
              </h1>
              <p style="margin:0; font-size:16px; line-height:1.6; color:#4b5563;">
                Please find attached the documents for the unit you requested. The leaflets provide
                general information, key features, and technical specifications, while the manuals
                offer detailed instructions and comprehensive technical content.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 24px 24px; font-family:Arial, sans-serif; color:#111827">
              <h2 style="margin:0 0 10px 0; font-size:18px; line-height:1.4; font-weight:bold;">
                {model_name}
              </h2>
              <ul style="margin:0 0 16px 20px; padding:0; font-size:16px; line-height:1.6; font-weight:bold; color:#4b5563">
              {product_html}
              </ul>
              {catalog_html}
            </td>
          </tr>
          <tr>
            <td style="padding:0 24px 24px 24px; font-family:Arial, sans-serif; color:#111827;">
              <h2 style="margin:0 0 10px 0; font-size:18px; line-height:1.4; font-weight:bold;">
                Need more help?
              </h2>
              <p style="margin:0; font-size:14px; line-height:1.6; color:#4b5563;">
                Call us at (786) 953-6706, or visit
                <a href="https://cooperandhunter.us" target="_blank"
                   style="color:#2563eb; text-decoration:underline;">cooperandhunter.us</a>
                for more information.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 24px;">
              <hr style="border:none; border-top:1px solid #e5e7eb; margin:0 0 16px 0;" />
            </td>
          </tr>
          <tr>
            <td align="center"
                style="padding:0 24px 24px 24px; font-family:Arial, sans-serif; font-size:11px; line-height:1.5; color:#9ca3af;">
              You're receiving this email because you requested product documents from our support line.<br>
              <span style="display:inline-block; margin-top:4px;">
                11250 West 36th ave Unit 100, Hialeah, FL 33028.
              </span><br>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _build_html(brand: str, model: str) -> str | None:
    """
    Assemble the email HTML for a given brand+model.
    Returns None if the brand+model combination is not in the catalog.
    """
    product_html = get_product_html(brand, model)
    if product_html is None:
        return None

    catalog_html = get_catalog_html(brand) or ""
    display_model = model.title()

    return _EMAIL_TEMPLATE.format(
        model_name=display_model,
        product_html=product_html,
        catalog_html=catalog_html,
    )


def _send_sync(to_email: str, brand: str, model: str, html_body: str) -> None:
    """Blocking SMTP send — runs in a thread executor."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{model.title()} Product Documents — Comfortside"
    msg["From"] = settings.gmail_sender
    msg["To"] = to_email

    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(settings.gmail_sender, settings.gmail_app_password)
        server.sendmail(settings.gmail_sender, to_email, msg.as_string())

    logger.info("Document email sent | to=%s brand=%s model=%s", to_email, brand, model)


async def send_documents_email(to_email: str, brand: str, model: str) -> str:
    """
    Build and send a product document email for the given brand+model.

    Returns a status string suitable for the agent tool return value.
    """
    html = _build_html(brand, model)
    if html is None:
        available = _list_available(brand)
        if available:
            return (
                f"No documents found for {brand} {model}. "
                f"Available models for {brand}: {available}."
            )
        return (
            f"No documents found for brand '{brand}'. "
            "Available brands: Cooper and Hunter, Olmo, Bravo."
        )

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _send_sync, to_email, brand, model, html)
    except Exception as exc:
        logger.error(
            "Failed to send document email | to=%s brand=%s model=%s error=%r",
            to_email, brand, model, exc,
        )
        return f"Email could not be sent ({exc})."

    return f"Document email for {brand} {model} sent to {to_email}."


def _list_available(brand: str) -> str:
    """Return a comma-separated list of known models for a brand."""
    from app.documents.catalog import PRODUCT_DOCS
    brand_lower = brand.lower().strip()
    models = [m.title() for b, m in PRODUCT_DOCS if b == brand_lower]
    return ", ".join(models) if models else ""
