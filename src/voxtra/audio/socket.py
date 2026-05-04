"""AudioSocket TCP server for bidirectional audio streaming with Asterisk.

Asterisk's res_audiosocket module connects to a TCP server and streams
raw audio over a simple framed protocol. This is much simpler than RTP/UDP
externalMedia — no NAT traversal, no codec negotiation, just a TCP socket.

Protocol (Asterisk AudioSocket):
    Each frame is:
        [1 byte type] [3 bytes length (network byte order)] [payload]

    Types:
        0x00 = UUID (channel UUID, 16 bytes)
        0x01 = Audio (raw audio data in the negotiated codec)
        0x02 = Silence
        0x03 = Hangup
        0xFF = Error

Usage with Asterisk dialplan::

    [from-carrier]
    exten = _X.,1,Stasis(voxtra)

Voxtra then uses ARI to connect the channel to AudioSocket via
the AudioSocket() dialplan application or via snoop channels.

For simpler integration, Voxtra creates the AudioSocket server
internally when ``call.audio_stream()`` or ``call.open_audio_socket()``
is called.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from collections.abc import AsyncIterator
from typing import Any

from voxtra.types import AudioChunk, AudioCodec

logger = logging.getLogger("voxtra.audio.socket")

# AudioSocket frame types
FRAME_UUID = 0x00
FRAME_AUDIO = 0x01
FRAME_SILENCE = 0x02
FRAME_HANGUP = 0x03
FRAME_ERROR = 0xFF


class AudioSocketConnection:
    """A single AudioSocket connection from Asterisk.

    Represents one active audio stream for a call. Provides
    async iteration for receiving audio and a send method for
    playing audio back.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        codec: AudioCodec = AudioCodec.ULAW,
        sample_rate: int = 8000,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self.codec = codec
        self.sample_rate = sample_rate
        self.channel_uuid: str = ""
        self._closed = False
        self._sequence = 0

    async def receive(self) -> AsyncIterator[AudioChunk]:
        """Receive audio chunks from Asterisk.

        Yields AudioChunk objects as audio frames arrive from the call.
        Stops when the connection is closed or a hangup frame is received.
        """
        while not self._closed:
            try:
                # Read frame header: 1 byte type + 3 bytes length
                header = await self._reader.readexactly(4)
                frame_type = header[0]
                payload_len = struct.unpack(">I", b"\x00" + header[1:4])[0]

                if payload_len > 0:
                    payload = await self._reader.readexactly(payload_len)
                else:
                    payload = b""

                if frame_type == FRAME_UUID:
                    self.channel_uuid = payload.hex()
                    logger.debug("AudioSocket UUID: %s", self.channel_uuid)

                elif frame_type == FRAME_AUDIO:
                    chunk = AudioChunk(
                        data=payload,
                        sample_rate=self.sample_rate,
                        channels=1,
                        codec=self.codec,
                        sequence=self._sequence,
                        duration_ms=(len(payload) / self.sample_rate) * 1000,
                    )
                    self._sequence += 1
                    yield chunk

                elif frame_type == FRAME_SILENCE:
                    # Yield a silence chunk
                    silence_len = payload_len if payload_len > 0 else 160
                    chunk = AudioChunk(
                        data=b"\x7f" * silence_len,  # μ-law silence
                        sample_rate=self.sample_rate,
                        channels=1,
                        codec=self.codec,
                        sequence=self._sequence,
                        duration_ms=(silence_len / self.sample_rate) * 1000,
                    )
                    self._sequence += 1
                    yield chunk

                elif frame_type == FRAME_HANGUP:
                    logger.info("AudioSocket hangup received (uuid=%s)", self.channel_uuid)
                    self._closed = True
                    break

                elif frame_type == FRAME_ERROR:
                    logger.error("AudioSocket error frame received")
                    self._closed = True
                    break

            except asyncio.IncompleteReadError:
                logger.debug("AudioSocket connection closed (EOF)")
                self._closed = True
                break
            except Exception as exc:
                if not self._closed:
                    logger.error("AudioSocket receive error: %s", exc)
                self._closed = True
                break

    async def send(self, chunk: AudioChunk) -> None:
        """Send an audio chunk to Asterisk (plays to caller).

        Args:
            chunk: AudioChunk with audio data to send.
        """
        if self._closed:
            return

        try:
            # Build AudioSocket frame: type(1) + length(3) + payload
            payload = chunk.data
            length_bytes = struct.pack(">I", len(payload))[1:]  # 3 bytes
            frame = bytes([FRAME_AUDIO]) + length_bytes + payload
            self._writer.write(frame)
            await self._writer.drain()
        except Exception as exc:
            if not self._closed:
                logger.error("AudioSocket send error: %s", exc)
                self._closed = True

    async def send_bytes(self, data: bytes) -> None:
        """Send raw audio bytes to Asterisk."""
        await self.send(AudioChunk(
            data=data,
            sample_rate=self.sample_rate,
            codec=self.codec,
        ))

    async def close(self) -> None:
        """Close the AudioSocket connection."""
        self._closed = True
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed


class AudioSocketServer:
    """TCP server that accepts AudioSocket connections from Asterisk.

    Asterisk connects to this server when the AudioSocket() dialplan
    application is executed or when Voxtra instructs it via ARI.

    Usage::

        server = AudioSocketServer(host="0.0.0.0", port=9092)
        await server.start()

        # Wait for a connection from a specific channel
        conn = await server.accept(timeout=10.0)

        # Stream audio
        async for chunk in conn.receive():
            # Process audio...
            response_audio = process(chunk)
            await conn.send(response_audio)

        await server.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 0,
        codec: AudioCodec = AudioCodec.ULAW,
        sample_rate: int = 8000,
    ) -> None:
        self.host = host
        self.port = port
        self.codec = codec
        self.sample_rate = sample_rate

        self._server: asyncio.Server | None = None
        self._pending: asyncio.Queue[AudioSocketConnection] = asyncio.Queue()
        self._connections: list[AudioSocketConnection] = []

    async def start(self) -> int:
        """Start the AudioSocket TCP server.

        Returns:
            The port the server is listening on (useful when port=0
            for dynamic port assignment).
        """
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self.host,
            port=self.port,
        )

        # Get the actual port (important when port=0)
        addr = self._server.sockets[0].getsockname()
        self.port = addr[1]

        logger.info("AudioSocket server listening on %s:%d", self.host, self.port)
        return self.port

    async def accept(self, timeout: float = 30.0) -> AudioSocketConnection:
        """Wait for and return the next AudioSocket connection.

        Args:
            timeout: Seconds to wait before raising TimeoutError.

        Returns:
            An AudioSocketConnection for the connected channel.
        """
        try:
            conn = await asyncio.wait_for(self._pending.get(), timeout=timeout)
            return conn
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"No AudioSocket connection received within {timeout}s"
            )

    async def stop(self) -> None:
        """Stop the server and close all connections."""
        for conn in self._connections:
            await conn.close()
        self._connections.clear()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        logger.info("AudioSocket server stopped")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a new incoming AudioSocket connection from Asterisk."""
        peer = writer.get_extra_info("peername")
        logger.info("AudioSocket connection from %s", peer)

        conn = AudioSocketConnection(
            reader=reader,
            writer=writer,
            codec=self.codec,
            sample_rate=self.sample_rate,
        )
        self._connections.append(conn)
        await self._pending.put(conn)

    @property
    def address(self) -> str:
        """Return the server address as host:port."""
        return f"{self.host}:{self.port}"

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()
