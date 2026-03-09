"""Event system for Voxtra.

Events are the core communication mechanism between layers.
Telephony adapters emit events, the router dispatches them,
and call handlers consume them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """All event types in the Voxtra system."""

    # Call lifecycle
    CALL_STARTED = "call.started"
    CALL_RINGING = "call.ringing"
    CALL_ANSWERED = "call.answered"
    CALL_ENDED = "call.ended"
    CALL_FAILED = "call.failed"
    CALL_TRANSFERRED = "call.transferred"

    # Media events
    MEDIA_STARTED = "media.started"
    MEDIA_STOPPED = "media.stopped"
    AUDIO_FRAME_RECEIVED = "audio.frame.received"
    AUDIO_FRAME_SENT = "audio.frame.sent"

    # AI pipeline events
    USER_SPEECH_STARTED = "user.speech.started"
    USER_SPEECH_ENDED = "user.speech.ended"
    USER_TRANSCRIPT = "user.transcript"
    USER_TRANSCRIPT_PARTIAL = "user.transcript.partial"
    AGENT_THINKING = "agent.thinking"
    AGENT_RESPONSE = "agent.response"
    AGENT_SPEECH_STARTED = "agent.speech.started"
    AGENT_SPEECH_ENDED = "agent.speech.ended"

    # Control events
    DTMF_RECEIVED = "dtmf.received"
    BARGE_IN = "barge_in"
    SILENCE_DETECTED = "silence.detected"
    TURN_ENDED = "turn.ended"

    # System events
    ERROR = "error"
    SESSION_CREATED = "session.created"
    SESSION_DESTROYED = "session.destroyed"


class VoxtraEvent(BaseModel):
    """Base event model for all Voxtra events.

    All events carry:
    - A unique event ID
    - The event type
    - A session ID linking it to a call
    - A timestamp
    - An arbitrary data payload
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    type: EventType
    session_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": False}


class CallStartedEvent(VoxtraEvent):
    """Emitted when a new inbound or outbound call begins."""

    type: EventType = EventType.CALL_STARTED
    caller_id: str = ""
    callee_id: str = ""
    direction: str = "inbound"


class CallEndedEvent(VoxtraEvent):
    """Emitted when a call ends."""

    type: EventType = EventType.CALL_ENDED
    reason: str = ""
    duration_seconds: float = 0.0


class UserTranscriptEvent(VoxtraEvent):
    """Emitted when STT produces a transcript of user speech."""

    type: EventType = EventType.USER_TRANSCRIPT
    text: str = ""
    confidence: float = 0.0
    is_final: bool = True


class AgentResponseEvent(VoxtraEvent):
    """Emitted when the LLM agent produces a response."""

    type: EventType = EventType.AGENT_RESPONSE
    text: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class DTMFEvent(VoxtraEvent):
    """Emitted when DTMF tones are detected."""

    type: EventType = EventType.DTMF_RECEIVED
    digit: str = ""


class ErrorEvent(VoxtraEvent):
    """Emitted when an error occurs."""

    type: EventType = EventType.ERROR
    error_type: str = ""
    message: str = ""
