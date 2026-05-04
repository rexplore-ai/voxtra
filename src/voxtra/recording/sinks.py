"""Recording sink abstractions.

Sinks decouple "the recording stopped" from "what to do with the file".
This is what makes Voxtra usable from a downstream service (e.g. Luso8)
that needs to upload to GCS, kick off transcription, or just log the
file path — without forking the library.

The contract is intentionally minimal:

* One method, :meth:`RecordingSink.on_recording_complete`.
* Best-effort — a failing sink must not break the call flow.
* Async, so sinks can do I/O without blocking the event loop.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("voxtra.recording")


@dataclass
class RecordingMetadata:
    """Information about a completed recording.

    The exact set of fields available depends on the telephony backend.
    ``file_path`` is a best-effort guess at where Asterisk wrote the
    file; deployments that move recordings (e.g. CDR-driven uploads)
    should treat it as a hint, not a guarantee.
    """

    session_id: str
    name: str
    file_path: str = ""
    duration_seconds: float | None = None
    format: str = "wav"
    extra: dict[str, Any] = field(default_factory=dict)


class RecordingSink(ABC):
    """Pluggable destination for finished call recordings.

    Implementations should be idempotent — sinks may be invoked more
    than once for the same recording during reconnects or retries.
    """

    @abstractmethod
    async def on_recording_complete(self, metadata: RecordingMetadata) -> None:
        """Handle a completed recording.

        Must not raise into the call pipeline; catch and log errors
        internally. The framework wraps this call in a try/except as a
        belt-and-braces measure but well-behaved sinks should never
        rely on that.
        """


class LocalFileSink(RecordingSink):
    """Default sink — recording stays where Asterisk wrote it.

    No-op except for a debug log. Useful as a placeholder when callers
    want recording on but have no upload path yet.
    """

    def __init__(self, base_dir: str | Path = "/var/spool/asterisk/recording") -> None:
        self.base_dir = Path(base_dir)

    async def on_recording_complete(self, metadata: RecordingMetadata) -> None:
        path = metadata.file_path or str(self.base_dir / f"{metadata.name}.{metadata.format}")
        logger.info(
            "Recording complete (local): session=%s name=%s path=%s",
            metadata.session_id, metadata.name, path,
        )


class WebhookSink(RecordingSink):
    """POST recording metadata to an HTTP endpoint.

    The receiver is responsible for downloading the file (e.g. via
    Asterisk's HTTP recording endpoint, or by SCPing it from the
    Asterisk box) and uploading it to long-term storage. Voxtra itself
    never reads recording bytes.

    Payload (JSON)::

        {
          "session_id": "...",
          "name": "...",
          "file_path": "/var/spool/asterisk/recording/luso8-...",
          "duration_seconds": 42.3,
          "format": "wav",
          "extra": {...}
        }
    """

    def __init__(
        self,
        url: str,
        *,
        signing_secret: str = "",
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url
        self.signing_secret = signing_secret
        self.timeout_seconds = timeout_seconds
        self._client = http_client
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def on_recording_complete(self, metadata: RecordingMetadata) -> None:
        if not self.url:
            return
        body = json.dumps(
            {
                "session_id": metadata.session_id,
                "name": metadata.name,
                "file_path": metadata.file_path,
                "duration_seconds": metadata.duration_seconds,
                "format": metadata.format,
                "extra": metadata.extra,
            },
            separators=(",", ":"),
        ).encode("utf-8")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.signing_secret:
            import hashlib
            import hmac
            headers["X-Voxtra-Signature"] = hmac.new(
                self.signing_secret.encode("utf-8"), body, hashlib.sha256
            ).hexdigest()

        client = await self._get_client()
        try:
            resp = await client.post(self.url, content=body, headers=headers)
            if resp.status_code >= 400:
                logger.warning(
                    "Recording webhook %s rejected with %d for %s",
                    self.url, resp.status_code, metadata.name,
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "Recording webhook delivery failed for %s: %s",
                metadata.name, exc,
            )


class CompositeSink(RecordingSink):
    """Fan a single recording event out to multiple sinks.

    Each sink is awaited independently with errors swallowed so a slow
    or broken sink can't starve the others.
    """

    def __init__(self, *sinks: RecordingSink) -> None:
        self.sinks: list[RecordingSink] = list(sinks)

    async def on_recording_complete(self, metadata: RecordingMetadata) -> None:
        for sink in self.sinks:
            try:
                await sink.on_recording_complete(metadata)
            except Exception:
                logger.exception(
                    "Sink %s failed for recording %s",
                    sink.__class__.__name__, metadata.name,
                )
