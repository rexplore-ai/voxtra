"""ElevenLabs TTS provider implementation.

ElevenLabs provides high-quality, low-latency streaming text-to-speech
suitable for real-time telephony applications.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from voxtra.ai.tts.base import BaseTTS
from voxtra.config import TTSConfig
from voxtra.exceptions import TTSError
from voxtra.media.audio import AudioFrame

logger = logging.getLogger("voxtra.ai.tts.elevenlabs")


class ElevenLabsTTS(BaseTTS):
    """ElevenLabs streaming Text-to-Speech provider.

    Requires the `elevenlabs` package::

        pip install voxtra[elevenlabs]

    Configuration::

        ai:
          tts:
            provider: elevenlabs
            api_key: "your-api-key"
            voice_id: "voice-id"
            model: "eleven_turbo_v2_5"
    """

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    async def connect(self) -> None:
        """Initialize the ElevenLabs client."""
        try:
            from elevenlabs.client import AsyncElevenLabs
        except ImportError:
            raise TTSError(
                "elevenlabs is required for ElevenLabsTTS. "
                "Install with: pip install voxtra[elevenlabs]"
            )

        if not self.config.api_key:
            raise TTSError("ElevenLabs API key is required")

        self._client = AsyncElevenLabs(api_key=self.config.api_key)
        logger.info("ElevenLabs TTS connected (voice=%s)", self.config.voice_id)

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        """Stream audio frames from ElevenLabs TTS.

        Uses ElevenLabs' streaming API to yield audio chunks
        as they are generated for minimum latency.
        """
        if self._client is None:
            raise TTSError("ElevenLabsTTS not connected. Call connect() first.")

        try:
            audio_stream = await self._client.text_to_speech.convert_as_stream(
                text=text,
                voice_id=self.config.voice_id,
                model_id=self.config.model or "eleven_turbo_v2_5",
                output_format=f"pcm_{self.config.sample_rate}",
            )

            async for chunk in audio_stream:
                if isinstance(chunk, bytes) and len(chunk) > 0:
                    yield AudioFrame(
                        data=chunk,
                        sample_rate=self.config.sample_rate,
                        channels=1,
                    )

        except Exception as exc:
            logger.error("ElevenLabs TTS synthesis failed: %s", exc)
            raise TTSError(f"TTS synthesis failed: {exc}") from exc

    async def synthesize_full(self, text: str) -> bytes:
        """Generate complete audio for a text utterance."""
        if self._client is None:
            raise TTSError("ElevenLabsTTS not connected. Call connect() first.")

        try:
            audio = await self._client.text_to_speech.convert(
                text=text,
                voice_id=self.config.voice_id,
                model_id=self.config.model or "eleven_turbo_v2_5",
                output_format=f"pcm_{self.config.sample_rate}",
            )
            return audio
        except Exception as exc:
            raise TTSError(f"TTS synthesis failed: {exc}") from exc

    async def disconnect(self) -> None:
        """Close the ElevenLabs client."""
        self._client = None
        logger.info("ElevenLabs TTS disconnected")
