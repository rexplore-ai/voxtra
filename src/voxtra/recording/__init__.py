"""Recording sinks — pluggable destinations for completed call recordings.

A :class:`RecordingSink` is invoked exactly once when a recording stops,
with metadata describing where the file lives. Sinks are how downstream
consumers (Luso8, S3 uploaders, transcription pipelines) get notified —
the library itself never persists recordings beyond what Asterisk does
on disk.

Usage::

    from voxtra.recording import WebhookSink

    sink = WebhookSink("https://api.example.com/webhooks/recording")

    async def handler(call):
        await call.answer()
        await call.record_start(sink=sink)
        await call.listen(timeout=30)
        await call.record_stop()  # sink fires here

Or set a default sink on the app so every recording goes through it::

    app = VoxtraApp(..., recording_sink=sink)
"""

from voxtra.recording.sinks import (
    CompositeSink,
    LocalFileSink,
    RecordingMetadata,
    RecordingSink,
    WebhookSink,
)

__all__ = [
    "RecordingSink",
    "RecordingMetadata",
    "LocalFileSink",
    "WebhookSink",
    "CompositeSink",
]
