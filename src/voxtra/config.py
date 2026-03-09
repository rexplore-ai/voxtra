"""Configuration system for Voxtra.

Supports both programmatic configuration via Pydantic models
and YAML file-based configuration for declarative setup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from voxtra.types import AudioCodec, MediaTransportType

# ---------------------------------------------------------------------------
# Telephony configuration
# ---------------------------------------------------------------------------

class AsteriskConfig(BaseModel):
    """Configuration for Asterisk ARI connection."""

    base_url: str = "http://localhost:8088"
    username: str = "asterisk"
    password: str = "asterisk"
    app_name: str = "voxtra"
    websocket_url: str = ""  # Derived from base_url if empty

    def model_post_init(self, __context: Any) -> None:
        if not self.websocket_url:
            ws_base = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
            self.websocket_url = f"{ws_base}/ari/events?app={self.app_name}"


class SIPTrunkConfig(BaseModel):
    """Configuration for a SIP trunk connection."""

    name: str = ""
    host: str = ""
    port: int = 5060
    username: str = ""
    password: str = ""
    transport: str = "udp"  # udp, tcp, tls
    codec: AudioCodec = AudioCodec.ULAW
    do_register: bool = True


class LiveKitConfig(BaseModel):
    """Configuration for LiveKit connection."""

    url: str = "ws://localhost:7880"
    api_key: str = ""
    api_secret: str = ""


class TelephonyConfig(BaseModel):
    """Top-level telephony configuration."""

    provider: str = "asterisk"  # asterisk, freeswitch, livekit
    asterisk: AsteriskConfig | None = None
    livekit: LiveKitConfig | None = None
    sip_trunks: list[SIPTrunkConfig] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Media configuration
# ---------------------------------------------------------------------------

class MediaConfig(BaseModel):
    """Configuration for media transport and audio processing."""

    transport: MediaTransportType = MediaTransportType.WEBSOCKET
    codec: AudioCodec = AudioCodec.ULAW
    sample_rate: int = 8000
    channels: int = 1
    frame_duration_ms: int = 20
    buffer_size_ms: int = 200
    enable_echo_cancellation: bool = False


# ---------------------------------------------------------------------------
# AI provider configuration
# ---------------------------------------------------------------------------

class STTConfig(BaseModel):
    """Speech-to-Text provider configuration."""

    provider: str = "deepgram"
    api_key: str = ""
    model: str = "nova-2"
    language: str = "en"
    interim_results: bool = True
    punctuate: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class TTSConfig(BaseModel):
    """Text-to-Speech provider configuration."""

    provider: str = "elevenlabs"
    api_key: str = ""
    voice_id: str = ""
    model: str = ""
    language: str = "en"
    sample_rate: int = 8000
    extra: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    """LLM / Agent provider configuration."""

    provider: str = "openai"
    api_key: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 1024
    system_prompt: str = "You are a helpful voice assistant."
    extra: dict[str, Any] = Field(default_factory=dict)


class VADConfig(BaseModel):
    """Voice Activity Detection configuration."""

    enabled: bool = True
    silence_threshold_ms: int = 500
    speech_threshold_ms: int = 200
    energy_threshold: float = 0.02


class AIConfig(BaseModel):
    """Top-level AI provider configuration."""

    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    vad: VADConfig = Field(default_factory=VADConfig)


# ---------------------------------------------------------------------------
# Route configuration
# ---------------------------------------------------------------------------

class RouteConfig(BaseModel):
    """Configuration for a single call route."""

    extension: str = ""
    number: str = ""
    agent: str = ""
    handler: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Top-level Voxtra configuration
# ---------------------------------------------------------------------------

class ServerConfig(BaseModel):
    """Configuration for the Voxtra control server."""

    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False


class VoxtraConfig(BaseModel):
    """Root configuration model for a Voxtra application.

    Can be loaded from a YAML file or constructed programmatically.
    """

    app_name: str = "voxtra"
    version: str = "0.1.0"
    telephony: TelephonyConfig = Field(default_factory=TelephonyConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    routes: list[RouteConfig] = Field(default_factory=list)
    server: ServerConfig = Field(default_factory=ServerConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> VoxtraConfig:
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            raw = yaml.safe_load(f)

        if raw is None:
            raw = {}

        return cls.model_validate(raw)

    def to_yaml(self, path: str | Path) -> None:
        """Write configuration to a YAML file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            yaml.dump(
                self.model_dump(exclude_defaults=True),
                f,
                default_flow_style=False,
                sort_keys=False,
            )
