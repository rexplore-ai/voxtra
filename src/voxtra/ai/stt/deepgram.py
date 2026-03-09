"""Deepgram STT provider implementation.

Deepgram provides real-time streaming speech-to-text with low latency,
making it ideal for telephony AI applications.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from voxtra.ai.stt.base import BaseSTT, TranscriptionResult
from voxtra.config import STTConfig
from voxtra.exceptions import STTError
from voxtra.media.audio import AudioFrame

logger = logging.getLogger("voxtra.ai.stt.deepgram")


class DeepgramSTT(BaseSTT):
    """Deepgram streaming Speech-to-Text provider.

    Requires the `deepgram-sdk` package::

        pip install voxtra[deepgram]

    Configuration::

        ai:
          stt:
            provider: deepgram
            api_key: "your-api-key"
            model: "nova-2"
            language: "en"
    """

    def __init__(self, config: STTConfig) -> None:
        super().__init__(config)
        self._client: Any = None
        self._connection: Any = None

    async def connect(self) -> None:
        """Initialize the Deepgram client and open a streaming connection."""
        try:
            from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
        except ImportError:
            raise STTError(
                "deepgram-sdk is required for DeepgramSTT. "
                "Install with: pip install voxtra[deepgram]"
            )

        if not self.config.api_key:
            raise STTError("Deepgram API key is required")

        self._client = DeepgramClient(self.config.api_key)
        logger.info("Deepgram STT connected (model=%s)", self.config.model)

    async def transcribe_stream(
        self, audio_stream: AsyncIterator[AudioFrame]
    ) -> AsyncIterator[TranscriptionResult]:
        """Stream audio frames to Deepgram and yield transcription results.

        This method connects to Deepgram's streaming API, sends audio
        frames as they arrive, and yields interim and final transcripts.
        """
        if self._client is None:
            raise STTError("DeepgramSTT not connected. Call connect() first.")

        try:
            from deepgram import LiveOptions
        except ImportError:
            raise STTError("deepgram-sdk is required")

        import asyncio

        results_queue: asyncio.Queue[TranscriptionResult] = asyncio.Queue()

        options = LiveOptions(
            model=self.config.model,
            language=self.config.language,
            punctuate=self.config.punctuate,
            interim_results=self.config.interim_results,
            encoding="linear16",
            sample_rate=8000,
            channels=1,
        )

        connection = self._client.listen.asynclive.v("1")

        async def on_message(_, result: Any, **kwargs: Any) -> None:
            transcript = result.channel.alternatives[0].transcript
            if transcript:
                await results_queue.put(
                    TranscriptionResult(
                        text=transcript,
                        confidence=result.channel.alternatives[0].confidence,
                        is_final=result.is_final,
                    )
                )

        connection.on("Results", on_message)

        await connection.start(options)

        try:
            async def send_audio() -> None:
                async for frame in audio_stream:
                    await connection.send(frame.data)
                await connection.finish()

            send_task = asyncio.create_task(send_audio())

            while not send_task.done() or not results_queue.empty():
                try:
                    result = await asyncio.wait_for(results_queue.get(), timeout=0.1)
                    yield result
                except asyncio.TimeoutError:
                    continue

        finally:
            await connection.finish()

    async def transcribe(self, audio_data: bytes) -> TranscriptionResult:
        """Transcribe a complete audio buffer using Deepgram's REST API."""
        if self._client is None:
            raise STTError("DeepgramSTT not connected. Call connect() first.")

        try:
            from deepgram import PrerecordedOptions
        except ImportError:
            raise STTError("deepgram-sdk is required")

        options = PrerecordedOptions(
            model=self.config.model,
            language=self.config.language,
            punctuate=self.config.punctuate,
        )

        source = {"buffer": audio_data, "mimetype": "audio/wav"}
        response = await self._client.listen.asyncrest.v("1").transcribe_file(source, options)

        transcript = response.results.channels[0].alternatives[0].transcript
        confidence = response.results.channels[0].alternatives[0].confidence

        return TranscriptionResult(
            text=transcript,
            confidence=confidence,
            is_final=True,
        )

    async def disconnect(self) -> None:
        """Close the Deepgram connection."""
        if self._connection is not None:
            await self._connection.finish()
            self._connection = None
        self._client = None
        logger.info("Deepgram STT disconnected")
