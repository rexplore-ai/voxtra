"""Abstract base class for Voice Activity Detection (VAD).

VAD is critical for telephony AI — it detects when the caller
starts and stops speaking, enabling turn-taking and barge-in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from voxtra.config import VADConfig
from voxtra.media.audio import AudioFrame
from voxtra.registry import registry


class VADState(StrEnum):
    """Current state of the voice activity detector."""

    SILENCE = "silence"
    SPEECH = "speech"
    UNCERTAIN = "uncertain"


class VADResult(BaseModel):
    """Result of processing an audio frame through VAD."""

    state: VADState = VADState.SILENCE
    confidence: float = 0.0
    speech_duration_ms: float = 0.0
    silence_duration_ms: float = 0.0


class BaseVAD(ABC):
    """Abstract interface for Voice Activity Detection.

    VAD processes audio frames and determines whether the caller
    is currently speaking. This drives:

    - **Turn detection**: Knowing when the user finished speaking
    - **Barge-in**: Detecting when the user interrupts the AI
    - **Silence detection**: Timeouts and end-of-utterance

    Example implementation::

        class MyVAD(BaseVAD):
            async def process_frame(self, frame):
                energy = calculate_energy(frame.data)
                if energy > self.config.energy_threshold:
                    return VADResult(state=VADState.SPEECH, confidence=0.9)
                return VADResult(state=VADState.SILENCE, confidence=0.9)
    """

    def __init__(self, config: VADConfig) -> None:
        self.config = config
        self._state = VADState.SILENCE
        self._speech_start_ms: float = 0.0
        self._silence_start_ms: float = 0.0

    @abstractmethod
    async def process_frame(self, frame: AudioFrame) -> VADResult:
        """Process a single audio frame and return the VAD result.

        Args:
            frame: An audio frame to analyze.

        Returns:
            VADResult indicating speech/silence state.
        """
        ...

    @abstractmethod
    async def reset(self) -> None:
        """Reset the VAD state for a new utterance."""
        ...

    @property
    def state(self) -> VADState:
        """Current VAD state."""
        return self._state

    def is_speaking(self) -> bool:
        """Check if the caller is currently speaking."""
        return self._state == VADState.SPEECH

    async def __aenter__(self) -> BaseVAD:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.reset()


@registry.register_vad("energy")
class EnergyVAD(BaseVAD):
    """Simple energy-based VAD implementation.

    Uses audio frame energy levels to detect speech. Suitable
    for basic use cases; production systems should use more
    sophisticated models (e.g., Silero VAD, WebRTC VAD).
    """

    def __init__(self, config: VADConfig) -> None:
        super().__init__(config)
        self._consecutive_speech_frames: int = 0
        self._consecutive_silence_frames: int = 0

    async def process_frame(self, frame: AudioFrame) -> VADResult:
        """Detect speech based on audio energy."""
        energy = self._compute_energy(frame.data)

        if energy > self.config.energy_threshold:
            self._consecutive_speech_frames += 1
            self._consecutive_silence_frames = 0

            speech_ms = self._consecutive_speech_frames * frame.duration_ms
            if speech_ms >= self.config.speech_threshold_ms:
                self._state = VADState.SPEECH
                return VADResult(
                    state=VADState.SPEECH,
                    confidence=min(energy / self.config.energy_threshold, 1.0),
                    speech_duration_ms=speech_ms,
                )
        else:
            self._consecutive_silence_frames += 1
            self._consecutive_speech_frames = 0

            silence_ms = self._consecutive_silence_frames * frame.duration_ms
            if silence_ms >= self.config.silence_threshold_ms:
                self._state = VADState.SILENCE
                return VADResult(
                    state=VADState.SILENCE,
                    confidence=0.9,
                    silence_duration_ms=silence_ms,
                )

        return VADResult(state=VADState.UNCERTAIN, confidence=0.5)

    async def reset(self) -> None:
        """Reset VAD state."""
        self._state = VADState.SILENCE
        self._consecutive_speech_frames = 0
        self._consecutive_silence_frames = 0

    @staticmethod
    def _compute_energy(audio_data: bytes) -> float:
        """Compute RMS energy of audio data (16-bit PCM)."""
        if len(audio_data) < 2:
            return 0.0

        import struct

        n_samples = len(audio_data) // 2
        if n_samples == 0:
            return 0.0

        samples = struct.unpack(f"<{n_samples}h", audio_data[: n_samples * 2])
        sum_squares = sum(s * s for s in samples)
        rms = (sum_squares / n_samples) ** 0.5

        # Normalize to 0.0 - 1.0 range (16-bit max = 32768)
        return rms / 32768.0
