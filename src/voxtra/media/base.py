"""Abstract base class for media transports.

Media transports handle the real-time bidirectional audio streaming
between the telephony infrastructure and the Voxtra AI pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from voxtra.config import MediaConfig
from voxtra.media.audio import AudioFrame


class BaseMediaTransport(ABC):
    """Abstract interface for media transports.

    A media transport is responsible for:
    - Receiving audio frames from the telephony side
    - Sending audio frames (TTS output) back to the caller
    - Managing the bidirectional audio stream lifecycle
    - Handling codec conversion if needed

    Implementations:
    - WebSocketMediaTransport: Uses Asterisk's chan_websocket
    - RTPMediaTransport: Direct RTP streaming (advanced)
    - LiveKitMediaTransport: Via LiveKit rooms

    Example implementation::

        class MyTransport(BaseMediaTransport):
            async def connect(self, endpoint):
                self._ws = await websockets.connect(endpoint)

            async def receive_audio(self):
                async for msg in self._ws:
                    yield AudioFrame(data=msg)

            async def send_audio(self, frame):
                await self._ws.send(frame.data)

            async def disconnect(self):
                await self._ws.close()
    """

    def __init__(self, config: MediaConfig) -> None:
        self.config = config
        self._connected = False

    @abstractmethod
    async def connect(self, endpoint: str = "") -> None:
        """Open the media transport connection.

        Args:
            endpoint: Transport-specific connection endpoint
                      (e.g., WebSocket URL, RTP address:port).
        """
        ...

    @abstractmethod
    async def receive_audio(self) -> AsyncIterator[AudioFrame]:
        """Receive audio frames from the telephony side.

        Yields:
            AudioFrame objects as they arrive from the caller.
        """
        ...
        yield  # type: ignore[misc]

    @abstractmethod
    async def send_audio(self, frame: AudioFrame) -> None:
        """Send an audio frame to the caller.

        Args:
            frame: AudioFrame containing TTS output or other audio.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the media transport connection."""
        ...

    @property
    def is_connected(self) -> bool:
        """Whether the transport is currently connected."""
        return self._connected

    async def __aenter__(self) -> BaseMediaTransport:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
