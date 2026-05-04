"""Tests for the RecordingSink abstraction."""

from __future__ import annotations

import json

import httpx
import pytest

from voxtra.recording import (
    CompositeSink,
    LocalFileSink,
    RecordingMetadata,
    WebhookSink,
)


def _meta(**overrides: object) -> RecordingMetadata:
    base = {
        "session_id": "session-1",
        "name": "voxtra-rec-1",
        "file_path": "/var/spool/asterisk/recording/voxtra-rec-1.wav",
        "duration_seconds": 12.3,
        "format": "wav",
    }
    base.update(overrides)
    return RecordingMetadata(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_local_file_sink_is_a_noop() -> None:
    sink = LocalFileSink()
    # Must not raise even with empty metadata.
    await sink.on_recording_complete(_meta(file_path=""))


@pytest.mark.asyncio
async def test_webhook_sink_posts_json_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = WebhookSink("https://example.com/recordings", http_client=client)

    await sink.on_recording_complete(_meta())
    await sink.aclose()

    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["session_id"] == "session-1"
    assert body["name"] == "voxtra-rec-1"
    assert body["duration_seconds"] == 12.3
    assert body["format"] == "wav"


@pytest.mark.asyncio
async def test_webhook_sink_signs_with_secret() -> None:
    import hashlib
    import hmac

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = WebhookSink(
        "https://example.com/recordings",
        signing_secret="hunter2",
        http_client=client,
    )

    await sink.on_recording_complete(_meta())

    sig = requests[0].headers["X-Voxtra-Signature"]
    expected = hmac.new(b"hunter2", requests[0].content, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(sig, expected)


@pytest.mark.asyncio
async def test_webhook_sink_skips_empty_url() -> None:
    sink = WebhookSink("")
    await sink.on_recording_complete(_meta())  # must not raise / not call client


@pytest.mark.asyncio
async def test_webhook_sink_swallows_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = WebhookSink("https://example.com/recordings", http_client=client)

    # Must not raise into the call pipeline.
    await sink.on_recording_complete(_meta())


@pytest.mark.asyncio
async def test_composite_sink_invokes_all() -> None:
    seen: list[str] = []

    class Recorder:
        def __init__(self, name: str) -> None:
            self.name = name

        async def on_recording_complete(self, meta: RecordingMetadata) -> None:
            seen.append(f"{self.name}:{meta.name}")

    composite = CompositeSink(Recorder("a"), Recorder("b"))  # type: ignore[arg-type]
    await composite.on_recording_complete(_meta())

    assert seen == ["a:voxtra-rec-1", "b:voxtra-rec-1"]


@pytest.mark.asyncio
async def test_composite_sink_isolates_failures() -> None:
    class Boom:
        async def on_recording_complete(self, meta: RecordingMetadata) -> None:
            raise RuntimeError("nope")

    seen: list[str] = []

    class OK:
        async def on_recording_complete(self, meta: RecordingMetadata) -> None:
            seen.append(meta.name)

    composite = CompositeSink(Boom(), OK())  # type: ignore[arg-type]
    # Must not propagate Boom's error.
    await composite.on_recording_complete(_meta())
    assert seen == ["voxtra-rec-1"]
