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
