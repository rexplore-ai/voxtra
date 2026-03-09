"""Tests for Voxtra CallSession."""

from __future__ import annotations

import asyncio

import pytest

from voxtra.events import EventType, VoxtraEvent
from voxtra.session import CallSession
from voxtra.types import CallDirection, CallState


class TestCallSession:
    def test_default_state(self) -> None:
        session = CallSession()
        assert session.state == CallState.RINGING
        assert session.direction == CallDirection.INBOUND
        assert session.id  # auto-generated
        assert session.metadata == {}
        assert session.history == []

    def test_custom_construction(self) -> None:
        session = CallSession(
            session_id="test-123",
            caller_id="+265888111111",
            callee_id="1000",
            direction=CallDirection.OUTBOUND,
        )
        assert session.id == "test-123"
        assert session.caller_id == "+265888111111"
        assert session.callee_id == "1000"
        assert session.direction == CallDirection.OUTBOUND

    @pytest.mark.asyncio
    async def test_context_store(self) -> None:
        session = CallSession()
        await session.set_context("language", "chichewa")
        val = await session.get_context("language")
        assert val == "chichewa"

    @pytest.mark.asyncio
    async def test_context_default(self) -> None:
        session = CallSession()
        val = await session.get_context("missing", "fallback")
        assert val == "fallback"

    @pytest.mark.asyncio
    async def test_push_and_receive_event(self) -> None:
        session = CallSession()
        event = VoxtraEvent(
            type=EventType.USER_TRANSCRIPT,
            session_id=session.id,
            data={"text": "hello"},
        )
        await session.push_event(event)
        received = await asyncio.wait_for(session._event_queue.get(), timeout=1.0)
        assert received.type == EventType.USER_TRANSCRIPT
        assert received.data["text"] == "hello"

    def test_agent_not_configured_raises(self) -> None:
        session = CallSession()
        with pytest.raises(RuntimeError, match="No AI agent configured"):
            _ = session.agent

    @pytest.mark.asyncio
    async def test_answer_no_telephony_raises(self) -> None:
        session = CallSession()
        with pytest.raises(RuntimeError, match="No telephony adapter"):
            await session.answer()

    @pytest.mark.asyncio
    async def test_say_no_tts_raises(self) -> None:
        session = CallSession()
        with pytest.raises(RuntimeError, match="No TTS provider"):
            await session.say("hello")

    @pytest.mark.asyncio
    async def test_listen_no_stt_raises(self) -> None:
        session = CallSession()
        with pytest.raises(RuntimeError, match="No STT provider"):
            await session.listen()

    @pytest.mark.asyncio
    async def test_hangup_no_telephony_raises(self) -> None:
        session = CallSession()
        with pytest.raises(RuntimeError, match="No telephony adapter"):
            await session.hangup()
