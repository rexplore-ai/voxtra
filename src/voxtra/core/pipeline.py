"""Voice pipeline — the real-time STT → LLM → TTS engine.

The VoicePipeline orchestrates the flow of audio through the AI
stack: receiving caller audio, transcribing it, generating a
response, synthesizing speech, and sending it back. It also
handles barge-in, turn detection, and interruption.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from voxtra.ai.llm.base import BaseAgent
from voxtra.ai.stt.base import BaseSTT
from voxtra.ai.tts.base import BaseTTS
from voxtra.ai.vad.base import BaseVAD, VADState
from voxtra.events import EventType, VoxtraEvent
from voxtra.media.audio import AudioFrame
from voxtra.media.base import BaseMediaTransport
from voxtra.media.buffer import AudioBuffer

logger = logging.getLogger("voxtra.core.pipeline")


class VoicePipeline:
    """Real-time voice AI pipeline.

    Orchestrates the full loop::

        Caller audio → STT → LLM → TTS → Caller playback

    Features:
    - Streaming STT for low-latency transcription
    - Streaming TTS for low-latency speech output
    - VAD for turn detection and barge-in
    - Interruption handling (stop TTS when caller speaks)
    - Event emission for all pipeline stages

    Usage::

        pipeline = VoicePipeline(
            media=transport,
            stt=deepgram,
            llm=openai_agent,
            tts=elevenlabs,
        )
        await pipeline.run(session_id="abc123")
    """

    def __init__(
        self,
        *,
        media: BaseMediaTransport,
        stt: BaseSTT,
        llm: BaseAgent,
        tts: BaseTTS,
        vad: BaseVAD | None = None,
        event_callback: Any | None = None,
    ) -> None:
        self.media = media
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.vad = vad
        self._event_callback = event_callback

        self._running = False
        self._is_speaking = False  # Whether the AI is currently speaking
        self._interrupted = False  # Whether the caller interrupted the AI
        self._audio_buffer = AudioBuffer(max_duration_ms=5000.0, min_drain_ms=100.0)

    async def run(self, session_id: str = "") -> None:
        """Run the voice pipeline for a single call session.

        This is the main loop that:
        1. Receives audio from the media transport
        2. Feeds it through VAD and STT
        3. Sends transcripts to the LLM
        4. Synthesizes responses via TTS
        5. Streams audio back to the caller

        Args:
            session_id: The session ID for event correlation.
        """
        self._running = True
        logger.info("Voice pipeline started for session %s", session_id)

        try:
            # Run receive and process concurrently
            receive_task = asyncio.create_task(
                self._receive_loop(session_id)
            )
            process_task = asyncio.create_task(
                self._process_loop(session_id)
            )

            await asyncio.gather(receive_task, process_task)

        except asyncio.CancelledError:
            logger.info("Voice pipeline cancelled for session %s", session_id)
        except Exception:
            logger.exception("Voice pipeline error for session %s", session_id)
        finally:
            self._running = False
            await self._audio_buffer.close()
            logger.info("Voice pipeline stopped for session %s", session_id)

    async def stop(self) -> None:
        """Stop the voice pipeline."""
        self._running = False
        await self._audio_buffer.close()

    async def _receive_loop(self, session_id: str) -> None:
        """Receive audio frames from the media transport and buffer them."""
        async for frame in self.media.receive_audio():
            if not self._running:
                break

            # Run VAD on each frame
            if self.vad is not None:
                vad_result = await self.vad.process_frame(frame)

                if vad_result.state == VADState.SPEECH and self._is_speaking:
                    # Barge-in: caller is speaking while AI is talking
                    self._interrupted = True
                    await self._emit_event(
                        session_id,
                        EventType.BARGE_IN,
                        {"speech_duration_ms": vad_result.speech_duration_ms},
                    )

                if vad_result.state == VADState.SPEECH:
                    await self._emit_event(
                        session_id,
                        EventType.USER_SPEECH_STARTED,
                        {},
                    )

                if vad_result.state == VADState.SILENCE and vad_result.silence_duration_ms > 0:
                    await self._emit_event(
                        session_id,
                        EventType.SILENCE_DETECTED,
                        {"silence_duration_ms": vad_result.silence_duration_ms},
                    )

            await self._audio_buffer.push(frame)

    async def _process_loop(self, session_id: str) -> None:
        """Process buffered audio through the STT → LLM → TTS pipeline."""

        async def audio_frame_generator() -> AsyncIterator[AudioFrame]:
            """Yield frames from the buffer for STT consumption."""
            async for frame in self._audio_buffer.stream():
                yield frame

        # Stream audio through STT
        async for transcript in self.stt.transcribe_stream(audio_frame_generator()):
            if not self._running:
                break

            if transcript.is_final and transcript.text.strip():
                logger.debug(
                    "Session %s: transcript='%s' (confidence=%.2f)",
                    session_id,
                    transcript.text,
                    transcript.confidence,
                )

                await self._emit_event(
                    session_id,
                    EventType.USER_TRANSCRIPT,
                    {"text": transcript.text, "confidence": transcript.confidence},
                )

                # Generate LLM response
                await self._emit_event(session_id, EventType.AGENT_THINKING, {})

                response = await self.llm.respond(transcript.text)

                await self._emit_event(
                    session_id,
                    EventType.AGENT_RESPONSE,
                    {"text": response.text},
                )

                # Synthesize and play response
                await self._speak(session_id, response.text)

            elif not transcript.is_final and transcript.text.strip():
                await self._emit_event(
                    session_id,
                    EventType.USER_TRANSCRIPT_PARTIAL,
                    {"text": transcript.text},
                )

    async def _speak(self, session_id: str, text: str) -> None:
        """Synthesize text and stream audio back to the caller.

        Handles interruption: if the caller barges in while the AI
        is speaking, TTS playback stops immediately.
        """
        self._is_speaking = True
        self._interrupted = False

        await self._emit_event(session_id, EventType.AGENT_SPEECH_STARTED, {"text": text})

        try:
            async for audio_frame in self.tts.synthesize(text):
                if self._interrupted or not self._running:
                    logger.debug("Session %s: speech interrupted", session_id)
                    break
                await self.media.send_audio(audio_frame)
        except Exception:
            logger.exception("Session %s: TTS playback error", session_id)
        finally:
            self._is_speaking = False
            await self._emit_event(session_id, EventType.AGENT_SPEECH_ENDED, {"text": text})

    async def _emit_event(
        self, session_id: str, event_type: EventType, data: dict[str, Any]
    ) -> None:
        """Emit a pipeline event via the callback."""
        if self._event_callback is not None:
            event = VoxtraEvent(
                type=event_type,
                session_id=session_id,
                data=data,
            )
            await self._event_callback(event)
