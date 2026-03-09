"""Shared type definitions for Voxtra."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Coroutine

# Type alias for async call handlers
CallHandler = Callable[..., Coroutine[Any, Any, None]]


class CallDirection(str, Enum):
    """Direction of a phone call."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallState(str, Enum):
    """State machine for a call's lifecycle."""

    RINGING = "ringing"
    ANSWERED = "answered"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    TRANSFERRING = "transferring"
    COMPLETED = "completed"
    FAILED = "failed"


class AudioCodec(str, Enum):
    """Supported audio codecs."""

    ULAW = "ulaw"      # G.711 μ-law (North America)
    ALAW = "alaw"      # G.711 A-law (Europe/international)
    PCM_S16LE = "pcm_s16le"  # Raw 16-bit signed little-endian
    OPUS = "opus"


class MediaTransportType(str, Enum):
    """Type of media transport."""

    WEBSOCKET = "websocket"
    RTP = "rtp"
    LIVEKIT = "livekit"


class ProviderType(str, Enum):
    """Types of AI providers."""

    STT = "stt"
    TTS = "tts"
    LLM = "llm"
    VAD = "vad"
