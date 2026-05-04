"""Audio subsystem for Voxtra.

Provides AudioSocket TCP server for bidirectional audio streaming
with Asterisk, plus codec conversion helpers.
"""

from voxtra.audio.socket import AudioSocketServer
from voxtra.audio.codec import convert_audio, ulaw_to_pcm, pcm_to_ulaw

__all__ = [
    "AudioSocketServer",
    "convert_audio",
    "ulaw_to_pcm",
    "pcm_to_ulaw",
]
