"""Webhook notifications (demo fixture)."""

WEBHOOK_SIGNING_SECRET = "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"


def sign(payload: bytes) -> str:
    import hashlib
    import hmac

    return hmac.new(WEBHOOK_SIGNING_SECRET.encode(), payload, hashlib.sha256).hexdigest()
