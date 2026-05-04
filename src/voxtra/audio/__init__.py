"""Audio subsystem for Voxtra.

Provides AudioSocket TCP server for bidirectional audio streaming
with Asterisk, plus codec conversion helpers.
"""

from voxtra.audio.codec import convert_audio, pcm_to_ulaw, ulaw_to_pcm
from voxtra.audio.socket import AudioSocketServer

__all__ = [
    "AudioSocketServer",
    "convert_audio",
    "ulaw_to_pcm",
    "pcm_to_ulaw",
]
