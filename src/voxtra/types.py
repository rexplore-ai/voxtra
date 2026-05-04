"""Shared type definitions for Voxtra.

Core types used across the library — audio primitives, call state,
SIP trunk configuration, and type aliases for handlers.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# Type alias for async call handlers
CallHandler = Callable[..., Coroutine[Any, Any, None]]


class CallDirection(StrEnum):
    """Direction of a phone call."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallState(StrEnum):
    """State machine for a call's lifecycle."""

    RINGING = "ringing"
    ANSWERED = "answered"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    TRANSFERRING = "transferring"
    COMPLETED = "completed"
    FAILED = "failed"


class AudioCodec(StrEnum):
    """Supported audio codecs."""

    ULAW = "ulaw"      # G.711 μ-law (North America / Africa)
    ALAW = "alaw"      # G.711 A-law (Europe/international)
    PCM_S16LE = "pcm_s16le"  # Raw 16-bit signed little-endian
    OPUS = "opus"


class MediaTransportType(StrEnum):
    """Type of media transport."""

    AUDIOSOCKET = "audiosocket"
    WEBSOCKET = "websocket"
    RTP = "rtp"
    LIVEKIT = "livekit"


class ProviderType(StrEnum):
    """Types of AI providers."""

    STT = "stt"
    TTS = "tts"
    LLM = "llm"
    VAD = "vad"


# ---------------------------------------------------------------------------
# Audio primitives
# ---------------------------------------------------------------------------

class AudioChunk(BaseModel):
    """A chunk of raw audio data flowing through Voxtra.

    This is the universal audio container. All components — media
    transports, STT, TTS — communicate using AudioChunk objects.
    """

    data: bytes = b""
    sample_rate: int = 8000
    channels: int = 1
    codec: AudioCodec = AudioCodec.ULAW
    timestamp_ms: float = 0.0
    duration_ms: float = 20.0
    sequence: int = 0

    model_config = {"arbitrary_types_allowed": True}

    @property
    def n_samples(self) -> int:
        """Number of audio samples in this chunk."""
        if self.codec in (AudioCodec.ULAW, AudioCodec.ALAW):
            return len(self.data)  # 1 byte per sample
        return len(self.data) // 2  # 16-bit PCM = 2 bytes per sample

    @property
    def is_empty(self) -> bool:
        return len(self.data) == 0


# ---------------------------------------------------------------------------
# SIP Trunk configuration model
# ---------------------------------------------------------------------------

class SIPTrunk(BaseModel):
    """SIP trunk configuration for connecting to a carrier.

    Used by TenantProvisioner to generate pjsip.conf fragments
    and by the admin API to accept trunk configuration from the UI.
    """

    host: str
    port: int = 5060
    username: str = ""
    password: str = ""
    realm: str = ""           # defaults to host if empty
    did: str = ""             # outbound caller ID in E.164
    transport: str = "udp"    # udp | tcp | tls
    codecs: list[str] = Field(default_factory=lambda: ["ulaw", "alaw"])

    def model_post_init(self, __context: Any) -> None:
        if not self.realm:
            self.realm = self.host
