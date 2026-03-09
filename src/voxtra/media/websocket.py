"""WebSocket media transport for Voxtra.

This transport uses WebSocket connections to stream audio between
Asterisk (via chan_websocket or External Media) and the Voxtra
AI pipeline. WebSocket is the recommended transport for development
because it handles framing and timing automatically.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from voxtra.config import MediaConfig
from voxtra.exceptions import MediaError
from voxtra.media.audio import AudioFrame
from voxtra.media.base import BaseMediaTransport
from voxtra.types import AudioCodec

logger = logging.getLogger("voxtra.media.websocket")


class WebSocketMediaTransport(BaseMediaTransport):
    """WebSocket-based media transport.

    Connects to Asterisk's chan_websocket or any WebSocket endpoint
    that streams raw audio frames.

    The transport:
    - Receives audio frames from the telephony side
    - Converts codecs as needed (e.g., μ-law → PCM)
    - Sends TTS audio back to the caller
    - Handles connection lifecycle and reconnection

    Configuration::

        media:
          transport: websocket
          codec: ulaw
          sample_rate: 8000
          frame_duration_ms: 20
    """

    def __init__(self, config: MediaConfig) -> None:
        super().__init__(config)
        self._ws: Any = None
        self._endpoint: str = ""
        self._sequence: int = 0

    async def connect(self, endpoint: str = "") -> None:
        """Open a WebSocket connection to the media endpoint.

        Args:
            endpoint: WebSocket URL (e.g., ws://localhost:8088/ws).
        """
        try:
            import websockets
        except ImportError:
            raise MediaError(
                "websockets is required for WebSocketMediaTransport. "
                "Install with: pip install websockets"
            )

        self._endpoint = endpoint
        if not endpoint:
            logger.warning("No WebSocket endpoint provided; transport in standby mode")
            self._connected = True
            return

        try:
            self._ws = await websockets.connect(endpoint)
            self._connected = True
            logger.info("WebSocket media transport connected to %s", endpoint)
        except Exception as exc:
            raise MediaError(f"Failed to connect to WebSocket endpoint: {exc}") from exc

    async def receive_audio(self) -> AsyncIterator[AudioFrame]:
        """Receive audio frames from the WebSocket connection.

        Each WebSocket message is expected to contain a single frame
        of audio data in the configured codec.
        """
        if self._ws is None:
            raise MediaError("WebSocket not connected")

        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    frame = AudioFrame(
                        data=message,
                        sample_rate=self.config.sample_rate,
                        channels=self.config.channels,
                        codec=self.config.codec,
                        duration_ms=self.config.frame_duration_ms,
                        sequence=self._sequence,
                    )
                    self._sequence += 1

                    # Convert to PCM for the AI pipeline
                    if frame.codec != AudioCodec.PCM_S16LE:
                        frame = frame.to_pcm_s16le()

                    yield frame
                else:
                    # Text messages might be control messages
                    logger.debug("Received text message on media WS: %s", message[:100])

        except Exception as exc:
            if self._connected:
                logger.error("WebSocket receive error: %s", exc)
                raise MediaError(f"WebSocket receive failed: {exc}") from exc

    async def send_audio(self, frame: AudioFrame) -> None:
        """Send an audio frame to the caller via WebSocket.

        The frame is converted to the configured codec before sending.
        """
        if self._ws is None:
            logger.debug("WebSocket not connected; dropping audio frame")
            return

        try:
            # Convert from PCM to the telephony codec
            from voxtra.media.audio import convert_audio

            if frame.codec != self.config.codec:
                data = convert_audio(
                    frame.data,
                    from_codec=frame.codec,
                    to_codec=self.config.codec,
                )
            else:
                data = frame.data

            await self._ws.send(data)

        except Exception as exc:
            logger.error("WebSocket send error: %s", exc)
            raise MediaError(f"WebSocket send failed: {exc}") from exc

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._connected = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        logger.info("WebSocket media transport disconnected")
