"""Backend webhook emitter — push Voxtra events to an external HTTP endpoint.

Voxtra is a library, not a service: most non-trivial deployments will host
Voxtra inside a larger application that needs to react to call-state
changes (CRM updates, billing, analytics). The :class:`BackendWebhook`
streams every :class:`~voxtra.events.VoxtraEvent` from a
:class:`~voxtra.app.VoxtraApp` to an HTTP URL, optionally signed with an
HMAC-SHA256 shared secret so the receiver can verify origin.

Usage::

    from voxtra import VoxtraApp
    from voxtra.webhooks import BackendWebhook
    from voxtra.config import WebhookConfig

    webhook = BackendWebhook(
        WebhookConfig(
            url="https://api.example.com/webhooks/voxtra",
            signing_secret="s3cret",
            events=["call.started", "call.answered", "call.ended"],
        ),
    )

    app = VoxtraApp(
        ari_url="http://pbx:8088",
        ari_user="asterisk",
        ari_password="secret",
        webhook=webhook,
    )

Receivers verify with::

    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, request.headers["X-Voxtra-Signature"])
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from voxtra.config import WebhookConfig
    from voxtra.events import VoxtraEvent

logger = logging.getLogger("voxtra.webhooks")


class BackendWebhook:
    """Async HTTP emitter for Voxtra events.

    Designed to be created once at application startup and shared across
    the lifetime of a :class:`VoxtraApp`. Internally owns an
    :class:`httpx.AsyncClient`, opened lazily on first ``emit`` and closed
    via :meth:`aclose`.

    Reliability model:

    * Emission is best-effort. The webhook never raises into the call
      pipeline — a failing receiver must not drop a customer's call.
    * On HTTP errors or 5xx responses the emitter retries with
      exponential backoff up to ``config.max_retries`` times.
    * 4xx responses are not retried (they indicate a contract bug, not
      a transient issue).
    * If all retries fail the event is logged at WARNING and dropped.
      For at-least-once delivery, persist events on the receiver side.
    """

    def __init__(
        self,
        config: WebhookConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._client = http_client
        self._owns_client = http_client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client (only if owned)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _should_emit(self, event: VoxtraEvent) -> bool:
        """Filter by config.events — empty list means emit everything."""
        if not self.config.events:
            return True
        return str(event.type) in self.config.events

    @staticmethod
    def _sign(body: bytes, secret: str) -> str:
        """Compute HMAC-SHA256 of the body using ``secret``."""
        return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def _build_payload(self, event: VoxtraEvent) -> dict[str, object]:
        """Build the JSON payload sent to the receiver.

        Pydantic's ``model_dump(mode='json')`` handles datetime / enum
        coercion so the receiver gets ISO-8601 timestamps and string
        event types.
        """
        return event.model_dump(mode="json")

    async def emit(self, event: VoxtraEvent) -> bool:
        """Fire-and-forget delivery of a single event.

        Returns True on a 2xx response (within the retry budget),
        False otherwise. Callers don't need to await this on the call
        path — wrap with ``asyncio.create_task`` to keep latency off the
        critical path.
        """
        if not self.config.url:
            return False
        if not self._should_emit(event):
            return False

        payload = self._build_payload(event)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "voxtra-webhook/1",
            "X-Voxtra-Event": str(event.type),
            "X-Voxtra-Event-Id": event.id,
            "X-Voxtra-Session-Id": event.session_id,
        }
        if self.config.signing_secret:
            headers["X-Voxtra-Signature"] = self._sign(body, self.config.signing_secret)

        client = await self._get_client()

        attempt = 0
        backoff = max(self.config.retry_backoff, 0.1)
        while True:
            try:
                resp = await client.post(self.config.url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    logger.debug(
                        "Webhook delivered: %s (status=%d, attempt=%d)",
                        event.type, resp.status_code, attempt + 1,
                    )
                    return True
                if 400 <= resp.status_code < 500:
                    logger.warning(
                        "Webhook %s rejected with %d — not retrying",
                        event.type, resp.status_code,
                    )
                    return False
                # 5xx — fall through to retry
                logger.info(
                    "Webhook %s got %d on attempt %d",
                    event.type, resp.status_code, attempt + 1,
                )
            except httpx.HTTPError as exc:
                logger.info(
                    "Webhook %s transport error on attempt %d: %s",
                    event.type, attempt + 1, exc,
                )

            attempt += 1
            if attempt > self.config.max_retries:
                logger.warning(
                    "Webhook %s dropped after %d attempts",
                    event.type, attempt,
                )
                return False
            await asyncio.sleep(backoff)
            backoff *= 2
