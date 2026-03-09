"""
Voxtra — Open voice infrastructure for AI agents.

Built by Rexplore Research Labs.

Voxtra bridges telephony infrastructure (Asterisk, FreeSWITCH, LiveKit)
with AI voice agents (STT, LLM, TTS) through a developer-friendly Python API.
"""

__version__ = "0.1.0"

from voxtra.app import VoxtraApp
from voxtra.session import CallSession
from voxtra.router import Router
from voxtra.events import VoxtraEvent, EventType
from voxtra.config import VoxtraConfig

__all__ = [
    "VoxtraApp",
    "CallSession",
    "Router",
    "VoxtraEvent",
    "EventType",
    "VoxtraConfig",
]
