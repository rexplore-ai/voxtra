"""ARI data models — typed representations of Asterisk resources."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Channel(BaseModel):
    """Represents an Asterisk channel (a single leg of a call)."""

    id: str = ""
    name: str = ""
    state: str = ""
    caller_number: str = ""
    caller_name: str = ""
    connected_number: str = ""
    connected_name: str = ""
    dialplan_context: str = ""
    dialplan_exten: str = ""
    dialplan_priority: int = 0
    language: str = "en"
    accountcode: str = ""
    creationtime: str = ""

    @classmethod
    def from_ari(cls, data: dict[str, Any]) -> Channel:
        """Parse a Channel from raw ARI JSON."""
        caller = data.get("caller", {})
        connected = data.get("connected", {})
        dialplan = data.get("dialplan", {})
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            state=data.get("state", ""),
            caller_number=caller.get("number", ""),
            caller_name=caller.get("name", ""),
            connected_number=connected.get("number", ""),
            connected_name=connected.get("name", ""),
            dialplan_context=dialplan.get("context", ""),
            dialplan_exten=dialplan.get("exten", ""),
            dialplan_priority=dialplan.get("priority", 0),
            language=data.get("language", "en"),
            accountcode=data.get("accountcode", ""),
            creationtime=data.get("creationtime", ""),
        )


class Bridge(BaseModel):
    """Represents an Asterisk bridge (mixes audio between channels)."""

    id: str = ""
    technology: str = ""
    bridge_type: str = ""
    bridge_class: str = ""
    name: str = ""
    channels: list[str] = Field(default_factory=list)

    @classmethod
    def from_ari(cls, data: dict[str, Any]) -> Bridge:
        return cls(
            id=data.get("id", ""),
            technology=data.get("technology", ""),
            bridge_type=data.get("bridge_type", ""),
            bridge_class=data.get("bridge_class", ""),
            name=data.get("name", ""),
            channels=data.get("channels", []),
        )


class Playback(BaseModel):
    """Represents an active audio playback on a channel."""

    id: str = ""
    media_uri: str = ""
    target_uri: str = ""
    language: str = "en"
    state: str = ""

    @classmethod
    def from_ari(cls, data: dict[str, Any]) -> Playback:
        return cls(
            id=data.get("id", ""),
            media_uri=data.get("media_uri", ""),
            target_uri=data.get("target_uri", ""),
            language=data.get("language", "en"),
            state=data.get("state", ""),
        )
