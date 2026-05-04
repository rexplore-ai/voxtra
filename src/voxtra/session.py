"""CallSession — the developer-facing handle for an active call.

A CallSession is created for every inbound or outbound call and
provides a high-level async API for full call control. This is the
primary object developers interact with inside call handlers.

The session wraps an ARIClient and provides:
- Call lifecycle: answer, hangup, hold, unhold, transfer
- Audio I/O: audio_stream(), send_audio(), play_file()
- DTMF: listen_dtmf(), send_dtmf()
- Recording: record_start(), record_stop()
- Bridging: bridge_with(), transfer_to_queue()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from voxtra.events import (
    EventType,
    VoxtraEvent,
)
from voxtra.types import AudioChunk, AudioCodec, CallDirection, CallState

if TYPE_CHECKING:
    from voxtra.ari.client import ARIClient
    from voxtra.audio.socket import AudioSocketConnection, AudioSocketServer

logger = logging.getLogger("voxtra.session")


class CallSession:
    """Represents a single active call with full control over audio.

    This is the call handle passed to every ``@app.on_call`` handler.
    All call operations go through this object::

        @app.on_call
        async def handle(call):
            await call.answer()
            await call.play_file("hello-world")

            async for chunk in call.audio_stream():
                # process caller audio...
                await call.send_audio(response_chunk)

            await call.hangup()

    Attributes:
        id: Unique call/session identifier (= Asterisk channel ID).
        caller_id: The calling party number.
        called_number: The dialed extension or DID.
        direction: "inbound" or "outbound".
        state: Current call state.
        metadata: Arbitrary key-value store for call context.
        duration: Seconds since the call was answered.
    """

    def __init__(
        self,
        *,
        channel_id: str,
        caller_id: str = "",
        called_number: str = "",
        direction: CallDirection = CallDirection.INBOUND,
        ari: ARIClient | None = None,
        app_name: str = "voxtra",
    ) -> None:
        self.id: str = channel_id
        self.caller_id = caller_id
        self.called_number = called_number
        self.direction = direction
        self.state = CallState.RINGING
        self.metadata: dict[str, Any] = {}
        self.app_name = app_name

        # Internal
        self._ari = ari
        self._answer_time: float | None = None
        self._audio_server: AudioSocketServer | None = None
        self._audio_conn: AudioSocketConnection | None = None
        self._bridge_id: str | None = None
        self._recording_name: str | None = None

        # Event queue for streaming events to the handler
        self._event_queue: asyncio.Queue[VoxtraEvent] = asyncio.Queue()

        # DTMF buffer
        self._dtmf_queue: asyncio.Queue[str] = asyncio.Queue()

        # Hangup callbacks
        self._on_hangup_callbacks: list[Any] = []
        self._on_dtmf_callbacks: list[Any] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def duration(self) -> float:
        """Seconds since the call was answered."""
        if self._answer_time is None:
            return 0.0
        return time.monotonic() - self._answer_time

    # ------------------------------------------------------------------
    # Call lifecycle
    # ------------------------------------------------------------------

    async def answer(self) -> None:
        """Answer the incoming call."""
        if self._ari is None:
            raise RuntimeError("No ARI client configured")
        await self._ari.answer_channel(self.id)
        self.state = CallState.ANSWERED
        self._answer_time = time.monotonic()
        logger.info("Session %s: call answered", self.id)

    async def hangup(self, reason: str = "normal") -> None:
        """Hang up the call."""
        if self.state == CallState.COMPLETED:
            return
        logger.info("Session %s: hanging up (reason=%s)", self.id, reason)
        self.state = CallState.COMPLETED
        await self._cleanup()
        if self._ari is not None:
            try:
                await self._ari.hangup_channel(self.id, reason=reason)
            except Exception:
                pass  # Channel may already be gone

    async def hold(self, moh_class: str = "default") -> None:
        """Place the call on hold (music on hold)."""
        if self._ari is None:
            raise RuntimeError("No ARI client configured")
        self.state = CallState.ON_HOLD
        await self._ari.moh_start(self.id, moh_class)
        logger.info("Session %s: on hold", self.id)

    async def unhold(self) -> None:
        """Take the call off hold."""
        if self._ari is None:
            raise RuntimeError("No ARI client configured")
        await self._ari.moh_stop(self.id)
        self.state = CallState.ANSWERED
        logger.info("Session %s: off hold", self.id)

    # ------------------------------------------------------------------
    # Audio playback (Asterisk sound files and URLs)
    # ------------------------------------------------------------------

    async def play_file(self, filename: str, lang: str = "") -> None:
        """Play an Asterisk sound file to the caller.

        Args:
            filename: Sound file name without extension (e.g. "hello-world").
            lang: Language variant (e.g. "en", "fr").
        """
        if self._ari is None:
            raise RuntimeError("No ARI client configured")
        pb = await self._ari.play_on_channel(
            self.id, f"sound:{filename}", lang=lang,
        )
        logger.debug("Session %s: playing file '%s' (playback=%s)", self.id, filename, pb.id)

    async def play_url(self, url: str) -> None:
        """Play audio from an HTTP URL to the caller.

        Args:
            url: HTTP(S) URL pointing to an audio file.
        """
        if self._ari is None:
            raise RuntimeError("No ARI client configured")
        pb = await self._ari.play_on_channel(self.id, url)
        logger.debug("Session %s: playing URL '%s' (playback=%s)", self.id, url, pb.id)

    async def stop_playback(self, playback_id: str) -> None:
        """Stop an active playback."""
        if self._ari is None:
            raise RuntimeError("No ARI client configured")
        await self._ari.stop_playback(playback_id)

    # ------------------------------------------------------------------
    # Audio streaming (raw audio I/O)
    # ------------------------------------------------------------------

    async def audio_stream(self) -> AsyncIterator[AudioChunk]:
        """Stream raw audio chunks from the caller.

        This is the primary method for receiving caller audio. It sets up
        an AudioSocket TCP server, instructs Asterisk to connect the
        channel's audio to it, and yields AudioChunk objects as they arrive.

        Usage::

            async for chunk in call.audio_stream():
                # chunk.data contains raw μ-law audio bytes
                transcript = await my_stt.transcribe(chunk.data)
        """
        conn = await self.open_audio_socket()
        async for chunk in conn.receive():
            yield chunk

    async def send_audio(self, chunk: AudioChunk) -> None:
        """Send an audio chunk to the caller.

        Args:
            chunk: AudioChunk containing audio data to play.
        """
        if self._audio_conn is None:
            raise RuntimeError(
                "No audio connection. Call audio_stream() or open_audio_socket() first."
            )
        await self._audio_conn.send(chunk)

    async def send_audio_bytes(self, data: bytes) -> None:
        """Send raw audio bytes to the caller (convenience method)."""
        await self.send_audio(AudioChunk(data=data))

    async def open_audio_socket(self) -> AudioSocketConnection:
        """Open an AudioSocket connection for bidirectional audio.

        Sets up a TCP server, creates an AudioSocket channel via ARI,
        and bridges it with the call channel.

        Returns:
            AudioSocketConnection for reading/writing audio.
        """
        if self._audio_conn is not None:
            return self._audio_conn

        from voxtra.audio.socket import AudioSocketServer

        # Start a local AudioSocket TCP server on a dynamic port
        self._audio_server = AudioSocketServer(host="0.0.0.0", port=0)
        port = await self._audio_server.start()

        if self._ari is None:
            raise RuntimeError("No ARI client configured")

        # Create a snoop channel that copies audio from the call channel
        # and connects it to our AudioSocket server.
        # Alternatively, create a bridge + externalMedia setup.
        # For now, we use the ARI snoop approach which gives us
        # bidirectional audio without modifying the dialplan.

        # Create a mixing bridge
        bridge = await self._ari.create_bridge(
            bridge_type="mixing",
            name=f"voxtra-audio-{self.id[:12]}",
        )
        self._bridge_id = bridge.id

        # Add the call channel to the bridge
        await self._ari.add_to_bridge(bridge.id, [self.id])

        # Create an external media channel pointing to our AudioSocket
        ext_channel = await self._ari.create_external_media(
            f"127.0.0.1:{port}",
            app=self.app_name,
            fmt="ulaw",
        )

        # Add external media to the same bridge
        await self._ari.add_to_bridge(bridge.id, [ext_channel.id])

        # Accept the incoming connection from Asterisk
        self._audio_conn = await self._audio_server.accept(timeout=10.0)

        logger.info(
            "Session %s: audio socket connected (port=%d, bridge=%s)",
            self.id, port, bridge.id,
        )

        return self._audio_conn

    # ------------------------------------------------------------------
    # DTMF
    # ------------------------------------------------------------------

    async def listen_dtmf(self, max_digits: int = 1, timeout: float = 10.0) -> str:
        """Wait for DTMF input from the caller.

        Args:
            max_digits: Number of digits to collect.
            timeout: Seconds to wait for input.

        Returns:
            The collected DTMF digit string (may be shorter than
            max_digits if timeout expires).
        """
        digits = ""
        deadline = asyncio.get_event_loop().time() + timeout

        while len(digits) < max_digits:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                digit = await asyncio.wait_for(
                    self._dtmf_queue.get(), timeout=remaining,
                )
                if digit == "#":
                    break  # # terminates input
                digits += digit
            except asyncio.TimeoutError:
                break

        return digits

    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF tones to the remote party."""
        if self._ari is None:
            raise RuntimeError("No ARI client configured")
        await self._ari.send_dtmf(self.id, digits)

    def on_dtmf(self, handler: Any) -> Any:
        """Register a DTMF event handler (decorator)."""
        self._on_dtmf_callbacks.append(handler)
        return handler

    # ------------------------------------------------------------------
    # Transfer
    # ------------------------------------------------------------------

    async def transfer_to(self, extension: str) -> None:
        """Blind transfer to a dialplan extension.

        Args:
            extension: Target extension or SIP endpoint.
        """
        if self._ari is None:
            raise RuntimeError("No ARI client configured")
        logger.info("Session %s: transferring to %s", self.id, extension)
        self.state = CallState.TRANSFERRING
        await self._ari.redirect_channel(self.id, f"PJSIP/{extension}")

    async def transfer_to_queue(
        self,
        queue: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Transfer the call to a human agent queue.

        Sets channel variables with context so the human agent
        can see the AI conversation summary, detected intent, etc.

        Args:
            queue: Queue name (e.g. "support", "sales").
            metadata: Context to forward — conversation summary, intent, etc.
        """
        if self._ari is None:
            raise RuntimeError("No ARI client configured")

        # Set channel variables with the metadata for the human agent
        if metadata:
            for key, value in metadata.items():
                await self._ari.set_channel_var(
                    self.id, f"VOXTRA_{key.upper()}", str(value),
                )

        logger.info("Session %s: transferring to queue '%s'", self.id, queue)
        self.state = CallState.TRANSFERRING

        # Redirect the channel to the queue context in the dialplan
        await self._ari.redirect_channel(
            self.id,
            f"Local/{queue}@agent-queues",
        )

    async def bridge_with(self, other: CallSession) -> str:
        """Bridge this call with another call (conference).

        Args:
            other: Another CallSession to bridge with.

        Returns:
            The bridge ID.
        """
        if self._ari is None:
            raise RuntimeError("No ARI client configured")

        bridge = await self._ari.create_bridge(
            bridge_type="mixing",
            name=f"voxtra-bridge-{uuid4().hex[:8]}",
        )
        await self._ari.add_to_bridge(bridge.id, [self.id, other.id])

        logger.info(
            "Session %s: bridged with %s (bridge=%s)",
            self.id, other.id, bridge.id,
        )
        return bridge.id

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record_start(self, name: str = "", fmt: str = "wav") -> str:
        """Start recording the call.

        Args:
            name: Recording name. Auto-generated if empty.
            fmt: Audio format (wav, gsm, etc.).

        Returns:
            The recording name (for retrieval later).
        """
        if self._ari is None:
            raise RuntimeError("No ARI client configured")

        if not name:
            name = f"voxtra-{self.id[:12]}-{uuid4().hex[:8]}"

        await self._ari.record_channel(self.id, name, fmt=fmt)
        self._recording_name = name
        logger.info("Session %s: recording started (%s)", self.id, name)
        return name

    async def record_stop(self) -> str | None:
        """Stop the current recording.

        Returns:
            The recording name, or None if not recording.
        """
        if self._recording_name is None:
            return None
        if self._ari is None:
            raise RuntimeError("No ARI client configured")

        name = self._recording_name
        await self._ari.stop_recording(name)
        self._recording_name = None
        logger.info("Session %s: recording stopped (%s)", self.id, name)
        return name

    # ------------------------------------------------------------------
    # Event callbacks
    # ------------------------------------------------------------------

    def on_hangup(self, handler: Any) -> Any:
        """Register a hangup event handler (decorator)."""
        self._on_hangup_callbacks.append(handler)
        return handler

    # ------------------------------------------------------------------
    # Internal event handling (used by VoxtraApp)
    # ------------------------------------------------------------------

    async def push_event(self, event: VoxtraEvent) -> None:
        """Push an event into this session's queue (used by the framework)."""
        await self._event_queue.put(event)

        # Route DTMF events to the DTMF queue
        if event.type == EventType.DTMF_RECEIVED:
            digit = event.data.get("digit", "")
            if digit:
                await self._dtmf_queue.put(digit)
                for cb in self._on_dtmf_callbacks:
                    try:
                        await cb(digit)
                    except Exception:
                        logger.exception("DTMF callback error")

        # Fire hangup callbacks
        if event.type == EventType.CALL_ENDED:
            for cb in self._on_hangup_callbacks:
                try:
                    await cb()
                except Exception:
                    logger.exception("Hangup callback error")

    async def _wait_for_event(self, event_type: EventType) -> VoxtraEvent:
        """Block until a specific event type arrives."""
        while True:
            event = await self._event_queue.get()
            if event.type == event_type:
                return event

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self) -> None:
        """Release all resources associated with this session."""
        if self._recording_name is not None:
            try:
                await self.record_stop()
            except Exception:
                pass

        if self._audio_conn is not None:
            await self._audio_conn.close()
            self._audio_conn = None

        if self._audio_server is not None:
            await self._audio_server.stop()
            self._audio_server = None

        if self._bridge_id is not None and self._ari is not None:
            try:
                await self._ari.destroy_bridge(self._bridge_id)
            except Exception:
                pass
            self._bridge_id = None
