"""Tests for Voxtra CallSession."""

from __future__ import annotations

import asyncio

import pytest

from voxtra.events import EventType, VoxtraEvent
from voxtra.session import CallSession
from voxtra.types import CallDirection, CallState


def _make_session(**kwargs) -> CallSession:
    """Helper to create a CallSession with defaults."""
    defaults = {"channel_id": "test-channel-001"}
    defaults.update(kwargs)
    return CallSession(**defaults)


class TestCallSession:
    def test_default_state(self) -> None:
        session = _make_session()
        assert session.state == CallState.RINGING
        assert session.direction == CallDirection.INBOUND
        assert session.id == "test-channel-001"
        assert session.metadata == {}

    def test_custom_construction(self) -> None:
        session = _make_session(
            channel_id="ch-123",
            caller_id="+265888111111",
            called_number="1000",
            direction=CallDirection.OUTBOUND,
        )
        assert session.id == "ch-123"
        assert session.caller_id == "+265888111111"
        assert session.called_number == "1000"
        assert session.direction == CallDirection.OUTBOUND

    def test_metadata_store(self) -> None:
        session = _make_session()
        session.metadata["language"] = "chichewa"
        assert session.metadata["language"] == "chichewa"

    def test_metadata_default(self) -> None:
        session = _make_session()
        val = session.metadata.get("missing", "fallback")
        assert val == "fallback"

    @pytest.mark.asyncio
    async def test_push_and_receive_event(self) -> None:
        session = _make_session()
        event = VoxtraEvent(
            type=EventType.USER_TRANSCRIPT,
            session_id=session.id,
            data={"text": "hello"},
        )
        await session.push_event(event)
        received = await asyncio.wait_for(session._event_queue.get(), timeout=1.0)
        assert received.type == EventType.USER_TRANSCRIPT
        assert received.data["text"] == "hello"

    @pytest.mark.asyncio
    async def test_dtmf_event_routes_to_dtmf_queue(self) -> None:
        session = _make_session()
        event = VoxtraEvent(
            type=EventType.DTMF_RECEIVED,
            session_id=session.id,
            data={"digit": "5"},
        )
        await session.push_event(event)
        digit = await asyncio.wait_for(session._dtmf_queue.get(), timeout=1.0)
        assert digit == "5"

    @pytest.mark.asyncio
    async def test_answer_no_ari_raises(self) -> None:
        session = _make_session()
        with pytest.raises(RuntimeError, match="No ARI client"):
            await session.answer()

    @pytest.mark.asyncio
    async def test_hold_no_ari_raises(self) -> None:
        session = _make_session()
        with pytest.raises(RuntimeError, match="No ARI client"):
            await session.hold()

    @pytest.mark.asyncio
    async def test_send_audio_no_connection_raises(self) -> None:
        from voxtra.types import AudioChunk
        session = _make_session()
        with pytest.raises(RuntimeError, match="No audio connection"):
            await session.send_audio(AudioChunk(data=b"\x00"))

    @pytest.mark.asyncio
    async def test_hangup_sets_completed(self) -> None:
        session = _make_session()
        # hangup without ARI should still set state to completed
        await session.hangup()
        assert session.state == CallState.COMPLETED

    @pytest.mark.asyncio
    async def test_hangup_idempotent(self) -> None:
        session = _make_session()
        await session.hangup()
        await session.hangup()  # should not raise
        assert session.state == CallState.COMPLETED

    def test_duration_zero_before_answer(self) -> None:
        session = _make_session()
        assert session.duration == 0.0

    @pytest.mark.asyncio
    async def test_on_hangup_callback(self) -> None:
        session = _make_session()
        called = []

        @session.on_hangup
        async def on_end():
            called.append(True)

        event = VoxtraEvent(
            type=EventType.CALL_ENDED,
            session_id=session.id,
            data={"reason": "test"},
        )
        await session.push_event(event)
        assert called == [True]

    @pytest.mark.asyncio
    async def test_on_dtmf_callback(self) -> None:
        session = _make_session()
        digits_received = []

        @session.on_dtmf
        async def on_digit(digit):
            digits_received.append(digit)

        event = VoxtraEvent(
            type=EventType.DTMF_RECEIVED,
            session_id=session.id,
            data={"digit": "3"},
        )
        await session.push_event(event)
        assert digits_received == ["3"]

    @pytest.mark.asyncio
    async def test_call_ended_dedupes_callbacks(self) -> None:
        """Multiple CALL_ENDED events (e.g. ARI StasisEnd + AudioSocket
        hangup for the same call) must fire hangup callbacks only once."""
        session = _make_session()
        call_count = 0

        @session.on_hangup
        async def on_end() -> None:
            nonlocal call_count
            call_count += 1

        ev1 = VoxtraEvent(
            type=EventType.CALL_ENDED,
            session_id=session.id,
            data={"source": "audiosocket"},
        )
        ev2 = VoxtraEvent(
            type=EventType.CALL_ENDED,
            session_id=session.id,
            data={"source": "ari"},
        )
        await session.push_event(ev1)
        await session.push_event(ev2)

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_audiosocket_hangup_propagates_to_session(self) -> None:
        """When the AudioSocket connection's on_hangup fires, the session
        must receive a CALL_ENDED event and run its hangup callbacks."""
        session = _make_session()
        called = []

        @session.on_hangup
        async def on_end() -> None:
            called.append(True)

        # Simulate what open_audio_socket() does: wire the session's
        # _on_audiosocket_hangup as the connection's on_hangup callback.
        await session._on_audiosocket_hangup()

        assert called == [True]
        # And subsequent CALL_ENDED from ARI should not double-fire.
        await session.push_event(
            VoxtraEvent(
                type=EventType.CALL_ENDED,
                session_id=session.id,
                data={"source": "ari"},
            )
        )
        assert called == [True]


class _FakeTTS:
    """Minimal TTS that yields one frame per word."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize(self, text: str):  # type: ignore[no-untyped-def]
        from voxtra.media.audio import AudioFrame
        from voxtra.types import AudioCodec
        self.calls.append(text)
        for word in text.split():
            yield AudioFrame(data=word.encode(), codec=AudioCodec.PCM_S16LE)


class _FakeMedia:
    """Minimal media transport collecting frames sent via send_audio."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send_audio(self, frame) -> None:  # type: ignore[no-untyped-def]
        self.sent.append(frame.data)


class _FakeLLM:
    """Records user inputs and returns a canned response."""

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def respond(  # type: ignore[no-untyped-def]
        self, text, *, history=None, system_prompt=None
    ):
        from voxtra.ai.llm.base import AgentResponse
        self.calls.append((text, list(history or [])))
        return AgentResponse(text=self.reply)


class TestSessionSayListenAgent:
    @pytest.mark.asyncio
    async def test_say_raises_without_pipeline(self) -> None:
        session = _make_session()
        with pytest.raises(RuntimeError, match="requires an AI pipeline"):
            await session.say("hello")

    @pytest.mark.asyncio
    async def test_listen_raises_without_pipeline(self) -> None:
        session = _make_session()
        with pytest.raises(RuntimeError, match="requires an AI pipeline"):
            await session.listen(timeout=0.05)

    @pytest.mark.asyncio
    async def test_agent_property_raises_without_pipeline(self) -> None:
        session = _make_session()
        with pytest.raises(RuntimeError, match="requires an AI pipeline"):
            _ = session.agent

    @pytest.mark.asyncio
    async def test_say_streams_through_media(self) -> None:
        session = _make_session()
        # Inject a stub pipeline-like object with the bits say() touches.
        tts = _FakeTTS()
        media = _FakeMedia()

        class _StubPipeline:
            pass

        stub = _StubPipeline()
        stub.tts = tts  # type: ignore[attr-defined]
        stub.media = media  # type: ignore[attr-defined]
        session._pipeline = stub  # type: ignore[assignment]

        await session.say("hello world")

        assert tts.calls == ["hello world"]
        assert media.sent == [b"hello", b"world"]

    @pytest.mark.asyncio
    async def test_listen_returns_user_transcript(self) -> None:
        session = _make_session()
        # Pipeline only needs to be non-None for listen().
        session._pipeline = object()  # type: ignore[assignment]

        # Push a non-transcript event first (to exercise filter), then the real one.
        await session.push_event(
            VoxtraEvent(
                type=EventType.AGENT_THINKING,
                session_id=session.id,
                data={},
            )
        )
        await session.push_event(
            VoxtraEvent(
                type=EventType.USER_TRANSCRIPT,
                session_id=session.id,
                data={"text": "hello voxtra"},
            )
        )

        text = await asyncio.wait_for(session.listen(timeout=1.0), timeout=2.0)
        assert text == "hello voxtra"

    @pytest.mark.asyncio
    async def test_listen_returns_empty_on_timeout(self) -> None:
        session = _make_session()
        session._pipeline = object()  # type: ignore[assignment]
        text = await session.listen(timeout=0.05)
        assert text == ""

    @pytest.mark.asyncio
    async def test_agent_respond_threads_history(self) -> None:
        session = _make_session()
        llm = _FakeLLM(reply="Sure!")

        class _StubPipeline:
            pass

        stub = _StubPipeline()
        stub.llm = llm  # type: ignore[attr-defined]
        session._pipeline = stub  # type: ignore[assignment]

        first = await session.agent.respond("Hi")
        second = await session.agent.respond("And again")

        assert first.text == "Sure!"
        assert second.text == "Sure!"
        # Second call's history should include the first user message AND
        # the assistant's first reply.
        _, history_at_second = llm.calls[1]
        assert history_at_second == [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Sure!"},
            {"role": "user", "content": "And again"},
        ]
        # Same agent client returned on each property access.
        assert session.agent is session.agent
