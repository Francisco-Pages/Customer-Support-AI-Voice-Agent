# Linq iMessage SMS — Archived Implementation

Archived on 2026-03-18 before migrating to ClickSend.

The full repo state at the time of archiving is also tagged in git:
    git show linq-sms-implementation:app/sms/linq_client.py
    git show linq-sms-implementation:app/routers/linq.py

## Files

- `linq_client.py` — async HTTP client for the Linq Partner API v3.
  Sends iMessages via a chat model (first message creates a chat, subsequent
  messages reuse the cached chatId from Redis).
  Public interface: `await send_sms(to="+1...", message="...")`

- `linq_router.py` — FastAPI router mounted at `/linq/webhook`.
  Receives inbound Linq webhook events, verifies HMAC-SHA256 signatures,
  and relays inbound messages to the active call session via Redis pub/sub
  (`sms_inbound:{phone}`).

## Config vars needed to reactivate

```
LINQ_API_TOKEN=...          # Bearer token from Linq dashboard
LINQ_FROM_NUMBER=+1...      # E.164 number provisioned on Linq
LINQ_WEBHOOK_SECRET=...     # Signing secret from webhook subscription (base64url-encoded)
```

## Notes

- chatId caching: Redis key `linq_chat:{e164_phone}`, TTL 24h
- Webhook signature: HMAC-SHA256 over `{timestamp}.{raw_body}`, headers
  `X-Webhook-Timestamp` and `X-Webhook-Signature`
- The signing algorithm was not fully verified with Linq support at the time
  of archiving (signature check was logging a warning but not hard-rejecting)
