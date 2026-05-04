"""
Voxtra — Open voice infrastructure for AI agents.

Built by Rexplore Research Labs.

Voxtra bridges Asterisk telephony with AI voice agents through a
developer-friendly Python API. 10 lines to a working call handler.

Quick start::

    from voxtra import VoxtraApp

    app = VoxtraApp(
        ari_url="http://pbx:8088",
        ari_user="asterisk",
        ari_password="secret",
    )

    @app.on_call
    async def handle(call):
        await call.answer()
        await call.play_file("hello-world")
        await call.hangup()

    app.run()
"""

__version__ = "0.2.0"

from voxtra.app import VoxtraApp
from voxtra.ari.client import ARIClient
from voxtra.audio.socket import AudioSocketServer
from voxtra.events import EventType, VoxtraEvent
from voxtra.session import CallSession
from voxtra.types import AudioChunk, SIPTrunk

__all__ = [
    "VoxtraApp",
    "CallSession",
    "ARIClient",
    "AudioSocketServer",
    "AudioChunk",
    "SIPTrunk",
    "VoxtraEvent",
    "EventType",
]
