"""Adapter that exposes a :class:`CallSession` as a :class:`BaseMediaTransport`.

The Voxtra codebase has two parallel media stacks: the AudioSocket /
AudioChunk stack used by ``CallSession``, and the MediaTransport /
AudioFrame stack used by ``VoicePipeline``. Direct interop is not
possible because :class:`AudioFrame` and :class:`AudioChunk` are
distinct Pydantic models with different default codecs.

:class:`CallSessionMediaTransport` is the single bridge between them.
It lets ``VoicePipeline`` consume a session's audio without callers
writing glue code.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from voxtra.media.audio import AudioFrame
from voxtra.media.base import BaseMediaTransport
from voxtra.session import CallSession
from voxtra.types import AudioCodec

logger = logging.getLogger("voxtra.media.session_transport")


class CallSessionMediaTransport(BaseMediaTransport):
    """Wrap a :class:`CallSession` as a :class:`BaseMediaTransport`.

    - :meth:`receive_audio` yields frames in ``target_codec`` (default
      PCM_S16LE — what STT providers expect).
    - :meth:`send_audio` accepts frames in any supported codec and
      converts them to the session's AudioSocket codec (μ-law typical).
    - :meth:`connect` and :meth:`disconnect` are no-ops; the underlying
      AudioSocket lifecycle is owned by :meth:`CallSession.open_audio_socket`
      and :meth:`CallSession.hangup`.
    """

    def __init__(
        self,
        session: CallSession,
        *,
        target_codec: AudioCodec = AudioCodec.PCM_S16LE,
    ) -> None:
        self.session = session
        self.target_codec = target_codec

    async def connect(self, endpoint: str = "") -> None:  # noqa: ARG002
        # The CallSession owns its AudioSocket lifecycle.
        return

    async def receive_audio(self) -> AsyncIterator[AudioFrame]:
        """Yield audio frames from the call's AudioSocket stream."""
        async for chunk in self.session.audio_stream():
            frame = AudioFrame.from_chunk(chunk)
            if frame.codec != self.target_codec:
                frame = frame.to_codec(self.target_codec)
            yield frame

    async def send_audio(self, frame: AudioFrame) -> None:
        """Send a frame to the caller, transcoding to the AudioSocket codec."""
        target_codec = self._session_codec()
        if frame.codec != target_codec:
            frame = frame.to_codec(target_codec)
        await self.session.send_audio(frame.to_chunk())

    async def disconnect(self) -> None:
        return

    @property
    def is_connected(self) -> bool:
        return not self.session._hangup_dispatched

    def _session_codec(self) -> AudioCodec:
        """Codec the session's AudioSocket expects.

        Defaults to μ-law if the AudioSocket connection hasn't been
        opened yet (typical for outbound flows that send before any
        inbound audio arrives).
        """
        conn = self.session._audio_conn
        if conn is not None:
            return conn.codec
        return AudioCodec.ULAW
