"""CallSession — the developer-facing handle for an active call.

A CallSession is created for every inbound or outbound call and
provides a high-level async API that hides telephony and media
complexity from the developer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator
from uuid import uuid4

from voxtra.events import (
    AgentResponseEvent,
    EventType,
    UserTranscriptEvent,
    VoxtraEvent,
)
from voxtra.types import CallDirection, CallState

if TYPE_CHECKING:
    from voxtra.ai.llm.base import BaseAgent
    from voxtra.ai.stt.base import BaseSTT
    from voxtra.ai.tts.base import BaseTTS
    from voxtra.media.base import BaseMediaTransport
    from voxtra.telephony.base import BaseTelephonyAdapter

logger = logging.getLogger("voxtra.session")


class CallSession:
    """Represents a single active call with full control over audio and AI.

    Developers interact with calls exclusively through this object::

        @app.route(extension="1000")
        async def handle(session: CallSession):
            await session.say("Hello!")
            text = await session.listen()
            reply = await session.agent.respond(text)
            await session.say(reply)

    Attributes:
        id: Unique session identifier.
        caller_id: The calling party number / SIP URI.
        callee_id: The called party number / extension.
        direction: Inbound or outbound.
        state: Current call state.
        metadata: Arbitrary key-value store for call context.
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        caller_id: str = "",
        callee_id: str = "",
        direction: CallDirection = CallDirection.INBOUND,
        telephony: BaseTelephonyAdapter | None = None,
        media: BaseMediaTransport | None = None,
        stt: BaseSTT | None = None,
        tts: BaseTTS | None = None,
        agent: BaseAgent | None = None,
        channel_id: str = "",
    ) -> None:
        self.id: str = session_id or uuid4().hex
        self.caller_id = caller_id
        self.callee_id = callee_id
        self.direction = direction
        self.state = CallState.RINGING
        self.channel_id = channel_id
        self.metadata: dict[str, Any] = {}

        # Internal components (injected by VoxtraApp)
        self._telephony = telephony
        self._media = media
        self._stt = stt
        self._tts = tts
        self._agent = agent

        # Event queue for streaming events to the handler
        self._event_queue: asyncio.Queue[VoxtraEvent] = asyncio.Queue()
        self._conversation_history: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent(self) -> BaseAgent:
        """Access the AI agent bound to this session."""
        if self._agent is None:
            raise RuntimeError("No AI agent configured for this session")
        return self._agent

    # ------------------------------------------------------------------
    # High-level voice API
    # ------------------------------------------------------------------

    async def answer(self) -> None:
        """Answer the incoming call."""
        if self._telephony is None:
            raise RuntimeError("No telephony adapter configured")
        await self._telephony.answer_call(self.channel_id)
        self.state = CallState.ANSWERED
        logger.info("Session %s: call answered", self.id)

    async def say(self, text: str) -> None:
        """Synthesize text and play it to the caller.

        This is the primary way to speak to the caller. Internally it:
        1. Sends text to TTS provider
        2. Receives audio frames
        3. Streams frames to the media transport
        """
        if self._tts is None:
            raise RuntimeError("No TTS provider configured")
        if self._media is None:
            raise RuntimeError("No media transport configured")

        logger.debug("Session %s: saying '%s'", self.id, text[:80])
        self._conversation_history.append({"role": "assistant", "content": text})

        async for audio_frame in self._tts.synthesize(text):
            await self._media.send_audio(audio_frame)

        await self._emit_event(EventType.AGENT_SPEECH_ENDED, {"text": text})

    async def listen(self, timeout: float = 30.0) -> str:
        """Listen for the caller's speech and return the transcript.

        Blocks until a final transcript is received or timeout expires.

        Args:
            timeout: Maximum seconds to wait for speech.

        Returns:
            The transcribed text from the caller.
        """
        if self._stt is None:
            raise RuntimeError("No STT provider configured")

        logger.debug("Session %s: listening (timeout=%.1fs)", self.id, timeout)

        try:
            event = await asyncio.wait_for(
                self._wait_for_event(EventType.USER_TRANSCRIPT),
                timeout=timeout,
            )
            text = event.data.get("text", "")
            self._conversation_history.append({"role": "user", "content": text})
            return text
        except asyncio.TimeoutError:
            logger.warning("Session %s: listen timeout", self.id)
            return ""

    async def stream(self) -> AsyncIterator[VoxtraEvent]:
        """Yield events as they arrive on this session.

        This is the low-level streaming API for handlers that want
        fine-grained control over the conversation flow::

            async for event in session.stream():
                if event.type == EventType.USER_TRANSCRIPT:
                    ...
                elif event.type == EventType.DTMF_RECEIVED:
                    ...
        """
        while self.state not in (CallState.COMPLETED, CallState.FAILED):
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                continue

    async def transfer(self, target: str) -> None:
        """Transfer the call to another extension or number.

        Args:
            target: Extension or SIP URI to transfer to.
        """
        if self._telephony is None:
            raise RuntimeError("No telephony adapter configured")
        logger.info("Session %s: transferring to %s", self.id, target)
        self.state = CallState.TRANSFERRING
        await self._telephony.transfer_call(self.channel_id, target)

    async def hangup(self) -> None:
        """Hang up the call."""
        if self._telephony is None:
            raise RuntimeError("No telephony adapter configured")
        logger.info("Session %s: hanging up", self.id)
        self.state = CallState.COMPLETED
        await self._telephony.hangup_call(self.channel_id)

    async def hold(self) -> None:
        """Place the call on hold."""
        if self._telephony is None:
            raise RuntimeError("No telephony adapter configured")
        self.state = CallState.ON_HOLD
        await self._telephony.hold_call(self.channel_id)

    async def play_audio(self, audio_data: bytes) -> None:
        """Play raw audio bytes to the caller."""
        if self._media is None:
            raise RuntimeError("No media transport configured")
        from voxtra.media.audio import AudioFrame

        frame = AudioFrame(data=audio_data)
        await self._media.send_audio(frame)

    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF tones to the remote party."""
        if self._telephony is None:
            raise RuntimeError("No telephony adapter configured")
        await self._telephony.send_dtmf(self.channel_id, digits)

    async def set_context(self, key: str, value: Any) -> None:
        """Store context data for the duration of the call."""
        self.metadata[key] = value

    async def get_context(self, key: str, default: Any = None) -> Any:
        """Retrieve stored context data."""
        return self.metadata.get(key, default)

    # ------------------------------------------------------------------
    # Conversation history
    # ------------------------------------------------------------------

    @property
    def history(self) -> list[dict[str, str]]:
        """Return the conversation history for this call."""
        return list(self._conversation_history)

    # ------------------------------------------------------------------
    # Internal event handling
    # ------------------------------------------------------------------

    async def push_event(self, event: VoxtraEvent) -> None:
        """Push an event into this session's queue (used by the framework)."""
        await self._event_queue.put(event)

    async def _wait_for_event(self, event_type: EventType) -> VoxtraEvent:
        """Block until a specific event type arrives."""
        while True:
            event = await self._event_queue.get()
            if event.type == event_type:
                return event

    async def _emit_event(self, event_type: EventType, data: dict[str, Any] | None = None) -> None:
        """Create and push an event into the session queue."""
        event = VoxtraEvent(
            type=event_type,
            session_id=self.id,
            data=data or {},
        )
        await self._event_queue.put(event)
