"""
Voxtra — Open voice infrastructure for AI agents.

Built by Rexplore Research Labs.

Voxtra bridges telephony infrastructure (Asterisk, FreeSWITCH, LiveKit)
with AI voice agents (STT, LLM, TTS) through a developer-friendly Python API.
"""

__version__ = "0.1.0b2"

from voxtra.app import VoxtraApp
from voxtra.config import VoxtraConfig
from voxtra.events import EventType, VoxtraEvent
from voxtra.router import Router
from voxtra.session import CallSession

__all__ = [
    "VoxtraApp",
    "CallSession",
    "Router",
    "VoxtraEvent",
    "EventType",
    "VoxtraConfig",
]
