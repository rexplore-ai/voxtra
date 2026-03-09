"""Media transport and audio processing for Voxtra.

This package handles real-time audio streaming between
telephony infrastructure and the AI voice pipeline.
"""

from voxtra.media.audio import AudioFrame
from voxtra.media.base import BaseMediaTransport

__all__ = ["AudioFrame", "BaseMediaTransport"]
