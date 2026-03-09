"""Core orchestration components for Voxtra.

Contains the voice pipeline that ties STT, LLM, and TTS
together into a real-time conversation engine.
"""

from voxtra.core.pipeline import VoicePipeline

__all__ = ["VoicePipeline"]
