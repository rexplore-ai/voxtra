"""ARI event parsing — translates raw Asterisk JSON events to typed objects."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from voxtra.ari.models import Channel


class ARIEvent(BaseModel):
    """A parsed ARI Stasis event."""

    type: str = ""
    application: str = ""
    timestamp: str = ""
    channel: Channel | None = None
    bridge_id: str = ""
    playback_id: str = ""
    digit: str = ""
    cause: int = 0
    cause_txt: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


def parse_ari_event(data: dict[str, Any]) -> ARIEvent:
    """Parse raw ARI WebSocket JSON into a typed ARIEvent."""
    channel_data = data.get("channel")
    channel = Channel.from_ari(channel_data) if channel_data else None

    playback_data = data.get("playback", {})

    return ARIEvent(
        type=data.get("type", ""),
        application=data.get("application", ""),
        timestamp=data.get("timestamp", ""),
        channel=channel,
        bridge_id=data.get("bridge", {}).get("id", ""),
        playback_id=playback_data.get("id", ""),
        digit=data.get("digit", ""),
        cause=data.get("cause", 0),
        cause_txt=data.get("cause_txt", ""),
        raw=data,
    )
