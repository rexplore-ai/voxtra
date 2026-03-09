"""Tests for Voxtra event system."""

from __future__ import annotations

from voxtra.events import (
    AgentResponseEvent,
    CallEndedEvent,
    CallStartedEvent,
    DTMFEvent,
    EventType,
    UserTranscriptEvent,
    VoxtraEvent,
)


class TestVoxtraEvent:
    def test_default_fields(self) -> None:
        event = VoxtraEvent(type=EventType.CALL_STARTED, session_id="abc")
        assert event.type == EventType.CALL_STARTED
        assert event.session_id == "abc"
        assert event.id  # auto-generated
        assert event.timestamp
        assert event.data == {}

    def test_custom_data(self) -> None:
        event = VoxtraEvent(
            type=EventType.ERROR,
            session_id="s1",
            data={"message": "something failed"},
        )
        assert event.data["message"] == "something failed"


class TestCallStartedEvent:
    def test_fields(self) -> None:
        event = CallStartedEvent(
            session_id="s1",
            caller_id="+265888111111",
            callee_id="1000",
            direction="inbound",
        )
        assert event.type == EventType.CALL_STARTED
        assert event.caller_id == "+265888111111"
        assert event.callee_id == "1000"
        assert event.direction == "inbound"


class TestCallEndedEvent:
    def test_fields(self) -> None:
        event = CallEndedEvent(
            session_id="s1",
            reason="hangup",
            duration_seconds=45.2,
        )
        assert event.type == EventType.CALL_ENDED
        assert event.reason == "hangup"
        assert event.duration_seconds == 45.2


class TestUserTranscriptEvent:
    def test_final_transcript(self) -> None:
        event = UserTranscriptEvent(
            session_id="s1",
            text="I need help with my bill",
            confidence=0.95,
            is_final=True,
        )
        assert event.type == EventType.USER_TRANSCRIPT
        assert event.text == "I need help with my bill"
        assert event.is_final is True

    def test_partial_transcript(self) -> None:
        event = UserTranscriptEvent(
            session_id="s1",
            text="I need",
            confidence=0.8,
            is_final=False,
        )
        assert event.is_final is False


class TestAgentResponseEvent:
    def test_fields(self) -> None:
        event = AgentResponseEvent(
            session_id="s1",
            text="I can help you with that.",
            tool_calls=[{"name": "lookup_account", "args": {"id": "123"}}],
        )
        assert event.type == EventType.AGENT_RESPONSE
        assert event.text == "I can help you with that."
        assert len(event.tool_calls) == 1


class TestDTMFEvent:
    def test_digit(self) -> None:
        event = DTMFEvent(session_id="s1", digit="5")
        assert event.type == EventType.DTMF_RECEIVED
        assert event.digit == "5"


class TestEventType:
    def test_all_types_are_strings(self) -> None:
        for et in EventType:
            assert isinstance(et.value, str)
            assert len(et.value) > 0
