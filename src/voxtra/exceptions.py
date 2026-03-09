"""Custom exceptions for Voxtra."""

from __future__ import annotations


class VoxtraError(Exception):
    """Base exception for all Voxtra errors."""


class ConfigurationError(VoxtraError):
    """Raised when configuration is invalid or missing."""


class TelephonyError(VoxtraError):
    """Raised when a telephony operation fails."""


class TelephonyConnectionError(TelephonyError):
    """Raised when connection to telephony backend fails."""


class CallError(VoxtraError):
    """Raised when a call operation fails."""


class MediaError(VoxtraError):
    """Raised when a media/audio operation fails."""


class CodecError(MediaError):
    """Raised when audio codec conversion fails."""


class ProviderError(VoxtraError):
    """Raised when an AI provider operation fails."""


class STTError(ProviderError):
    """Raised when speech-to-text fails."""


class TTSError(ProviderError):
    """Raised when text-to-speech fails."""


class LLMError(ProviderError):
    """Raised when LLM inference fails."""


class RouteNotFoundError(VoxtraError):
    """Raised when no route matches an incoming call."""


class SessionError(VoxtraError):
    """Raised when a call session operation fails."""


class PipelineError(VoxtraError):
    """Raised when the voice pipeline encounters an error."""
