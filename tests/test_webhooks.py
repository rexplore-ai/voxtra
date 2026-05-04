"""Tests for the BackendWebhook emitter."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from voxtra.config import WebhookConfig
from voxtra.events import EventType, VoxtraEvent
from voxtra.webhooks import BackendWebhook


def _make_event(event_type: EventType = EventType.CALL_STARTED, **data: object) -> VoxtraEvent:
    return VoxtraEvent(type=event_type, session_id="test-session", data=dict(data))


def _mock_transport(record: list[httpx.Request], status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        record.append(request)
        return httpx.Response(status, json={"ok": True})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_emit_skips_when_url_empty() -> None:
    webhook = BackendWebhook(WebhookConfig(url=""))
    delivered = await webhook.emit(_make_event())
    assert delivered is False


@pytest.mark.asyncio
async def test_emit_posts_event_payload() -> None:
    requests: list[httpx.Request] = []
    transport = _mock_transport(requests)
    client = httpx.AsyncClient(transport=transport)

    webhook = BackendWebhook(
        WebhookConfig(url="https://example.com/hook"),
        http_client=client,
    )

    event = _make_event(caller_id="+1234")
    delivered = await webhook.emit(event)

    assert delivered is True
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "POST"
    assert req.url == "https://example.com/hook"

    body = json.loads(req.content)
    assert body["type"] == "call.started"
    assert body["session_id"] == "test-session"
    assert body["data"]["caller_id"] == "+1234"

    assert req.headers["X-Voxtra-Event"] == "call.started"
    assert req.headers["X-Voxtra-Session-Id"] == "test-session"
    assert req.headers["X-Voxtra-Event-Id"] == event.id


@pytest.mark.asyncio
async def test_emit_signs_with_hmac_when_secret_set() -> None:
    requests: list[httpx.Request] = []
    transport = _mock_transport(requests)
    client = httpx.AsyncClient(transport=transport)

    secret = "super-secret"
    webhook = BackendWebhook(
        WebhookConfig(url="https://example.com/hook", signing_secret=secret),
        http_client=client,
    )

    await webhook.emit(_make_event())

    req = requests[0]
    sig = req.headers["X-Voxtra-Signature"]
    expected = hmac.new(secret.encode(), req.content, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(sig, expected)


@pytest.mark.asyncio
async def test_emit_filters_by_event_allowlist() -> None:
    requests: list[httpx.Request] = []
    transport = _mock_transport(requests)
    client = httpx.AsyncClient(transport=transport)

    webhook = BackendWebhook(
        WebhookConfig(
            url="https://example.com/hook",
            events=["call.ended"],  # only emit ended
        ),
        http_client=client,
    )

    delivered_started = await webhook.emit(_make_event(EventType.CALL_STARTED))
    delivered_ended = await webhook.emit(_make_event(EventType.CALL_ENDED))

    assert delivered_started is False
    assert delivered_ended is True
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_emit_does_not_retry_on_4xx() -> None:
    requests: list[httpx.Request] = []
    transport = _mock_transport(requests, status=400)
    client = httpx.AsyncClient(transport=transport)

    webhook = BackendWebhook(
        WebhookConfig(url="https://example.com/hook", max_retries=3, retry_backoff=0.01),
        http_client=client,
    )

    delivered = await webhook.emit(_make_event())

    assert delivered is False
    assert len(requests) == 1  # no retries on 4xx


@pytest.mark.asyncio
async def test_emit_retries_on_5xx_then_drops() -> None:
    requests: list[httpx.Request] = []
    transport = _mock_transport(requests, status=503)
    client = httpx.AsyncClient(transport=transport)

    webhook = BackendWebhook(
        WebhookConfig(url="https://example.com/hook", max_retries=2, retry_backoff=0.01),
        http_client=client,
    )

    delivered = await webhook.emit(_make_event())

    assert delivered is False
    # initial + 2 retries = 3 attempts
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_emit_retries_then_succeeds() -> None:
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    webhook = BackendWebhook(
        WebhookConfig(url="https://example.com/hook", max_retries=5, retry_backoff=0.01),
        http_client=client,
    )

    delivered = await webhook.emit(_make_event())

    assert delivered is True
    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_emit_swallows_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    webhook = BackendWebhook(
        WebhookConfig(url="https://example.com/hook", max_retries=1, retry_backoff=0.01),
        http_client=client,
    )

    # Must not raise. Returns False after retry budget.
    delivered = await webhook.emit(_make_event())
    assert delivered is False


@pytest.mark.asyncio
async def test_aclose_only_closes_owned_client() -> None:
    external = httpx.AsyncClient()
    webhook = BackendWebhook(
        WebhookConfig(url="https://example.com/hook"),
        http_client=external,
    )
    await webhook.aclose()
    # External client must NOT be closed
    assert not external.is_closed
    await external.aclose()


@pytest.mark.asyncio
async def test_emit_concurrent_calls_share_client() -> None:
    """Concurrent emissions must not race the lazy client init."""
    requests: list[httpx.Request] = []
    webhook = BackendWebhook(WebhookConfig(url="https://example.com/hook"))

    # Inject the client manually to avoid hitting the network.
    transport = _mock_transport(requests)
    webhook._client = httpx.AsyncClient(transport=transport)
    webhook._owns_client = True

    await asyncio.gather(*(webhook.emit(_make_event()) for _ in range(10)))
    await webhook.aclose()

    assert len(requests) == 10
