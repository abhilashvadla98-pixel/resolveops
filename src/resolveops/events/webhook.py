import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime

from resolveops.events.errors import WebhookAuthenticationError
from resolveops.events.models import WebhookHeaders


class WebhookVerifier:
    def __init__(
        self,
        secret: str,
        *,
        tolerance_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("webhook secret must contain at least 32 characters")
        if tolerance_seconds <= 0:
            raise ValueError("webhook tolerance must be positive")
        self.secret = secret.encode("utf-8")
        self.tolerance_seconds = tolerance_seconds
        self.clock = clock or (lambda: datetime.now(UTC))

    def sign(self, body: bytes, timestamp: int) -> str:
        signed_payload = str(timestamp).encode("ascii") + b"." + body
        digest = hmac.new(self.secret, signed_payload, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def verify(self, body: bytes, *, timestamp: str | None, signature: str | None) -> None:
        try:
            headers = WebhookHeaders.model_validate(
                {"timestamp": timestamp, "signature": signature}
            )
        except ValueError as exc:
            raise WebhookAuthenticationError(
                "invalid_webhook_authentication",
                "webhook authentication headers are missing or malformed",
            ) from exc
        now_timestamp = int(self.clock().timestamp())
        if abs(now_timestamp - headers.timestamp) > self.tolerance_seconds:
            raise WebhookAuthenticationError(
                "expired_webhook_timestamp",
                "webhook timestamp is outside the accepted replay window",
            )
        expected = self.sign(body, headers.timestamp)
        if not hmac.compare_digest(expected, headers.signature):
            raise WebhookAuthenticationError(
                "invalid_webhook_signature",
                "webhook signature did not match",
            )
