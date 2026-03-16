from fastapi import HTTPException, Header, Query, Request, status
from twilio.request_validator import RequestValidator

from app.config import settings


def validate_twilio_signature(request: Request, body: dict) -> None:
    """
    Validates that an inbound webhook request genuinely originated from Twilio.
    Raises HTTP 403 if the signature is invalid.

    Twilio computes a signature over: URL + sorted POST params.
    See: https://www.twilio.com/docs/usage/webhooks/webhooks-security
    """
    validator = RequestValidator(settings.twilio_auth_token)

    # Reconstruct the full URL Twilio signed against
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    url = str(request.url).replace(request.url.scheme, forwarded_proto)

    signature = request.headers.get("x-twilio-signature", "")

    if not validator.validate(url, body, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature.",
        )


def verify_admin_api_key(
    x_api_key: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> str:
    """
    Validates the API key for admin endpoints.
    Accepts the key via X-Api-Key header (normal API calls) or
    ?token= query param (browser-native elements like <audio src="...">).
    """
    key = x_api_key or token
    if key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    return key
