"""Abstract base class for Text-to-Speech providers.

All TTS implementations must subclass BaseTTS and implement
the streaming synthesis interface for low-latency audio output.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from voxtra.config import TTSConfig
from voxtra.media.audio import AudioFrame


class BaseTTS(ABC):
    """Abstract interface for Text-to-Speech providers.

    Implementations must support streaming synthesis — returning
    audio frames as they are generated rather than waiting for
    the entire utterance to complete. This is critical for
    low-latency telephony applications.

    Example implementation::

        class MyTTS(BaseTTS):
            async def connect(self):
                self._client = await create_tts_client(self.config.api_key)

            async def synthesize(self, text):
                async for chunk in self._client.stream(text):
                    yield AudioFrame(data=chunk, sample_rate=8000)

            async def synthesize_full(self, text):
                audio = await self._client.generate(text)
                return audio

            async def disconnect(self):
                await self._client.close()
    """

    def __init__(self, config: TTSConfig) -> None:
        self.config = config

    @abstractmethod
    async def connect(self) -> None:
        """Initialize connection to the TTS service."""
        ...

    @abstractmethod
    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        """Synthesize text into streaming audio frames.

        This is the primary method for telephony use. Audio frames
        are yielded as they become available for minimal latency.

        Args:
            text: The text to synthesize.

        Yields:
            AudioFrame objects containing audio data.
        """
        ...
        yield  # type: ignore[misc]

    @abstractmethod
    async def synthesize_full(self, text: str) -> bytes:
        """Synthesize text into a complete audio buffer.

        Use this for short utterances or pre-caching.

        Args:
            text: The text to synthesize.

        Returns:
            Complete audio data as bytes.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the TTS connection and release resources."""
        ...

    async def __aenter__(self) -> BaseTTS:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
