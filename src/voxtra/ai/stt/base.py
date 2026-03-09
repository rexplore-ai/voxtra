"""Abstract base class for Speech-to-Text providers.

All STT implementations must subclass BaseSTT and implement
the streaming transcription interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from pydantic import BaseModel

from voxtra.config import STTConfig
from voxtra.media.audio import AudioFrame


class TranscriptionResult(BaseModel):
    """A single transcription result from an STT provider."""

    text: str = ""
    confidence: float = 0.0
    is_final: bool = True
    language: str = ""
    words: list[dict[str, Any]] = []
    duration_seconds: float = 0.0


class BaseSTT(ABC):
    """Abstract interface for Speech-to-Text providers.

    Implementations must handle streaming audio input and produce
    transcription results. The framework expects providers to support
    both streaming (interim results) and batch modes.

    Example implementation::

        class MySTT(BaseSTT):
            async def connect(self):
                self._client = await create_connection(self.config.api_key)

            async def transcribe_stream(self, audio_stream):
                async for frame in audio_stream:
                    result = await self._client.send(frame.data)
                    yield TranscriptionResult(text=result.text, is_final=result.is_final)

            async def transcribe(self, audio_data):
                result = await self._client.recognize(audio_data)
                return TranscriptionResult(text=result.text)

            async def disconnect(self):
                await self._client.close()
    """

    def __init__(self, config: STTConfig) -> None:
        self.config = config

    @abstractmethod
    async def connect(self) -> None:
        """Initialize connection to the STT service."""
        ...

    @abstractmethod
    async def transcribe_stream(
        self, audio_stream: AsyncIterator[AudioFrame]
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe a stream of audio frames in real time.

        Args:
            audio_stream: Async iterator of AudioFrame objects.

        Yields:
            TranscriptionResult objects (both interim and final).
        """
        ...
        yield  # type: ignore[misc]

    @abstractmethod
    async def transcribe(self, audio_data: bytes) -> TranscriptionResult:
        """Transcribe a complete audio buffer (batch mode).

        Args:
            audio_data: Raw audio bytes.

        Returns:
            A single TranscriptionResult.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the STT connection and release resources."""
        ...

    async def __aenter__(self) -> BaseSTT:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
