"""Tests for AsteriskAdapter event translation and configuration.

The adapter wraps ARIClient — these tests cover the translation layer
(ARIEvent → VoxtraEvent) and the config-driven construction path.
Connect/listen tests live in the integration suite since they require
a live or mocked ARI WebSocket.
"""

from __future__ import annotations

import pytest

from voxtra.ari.events import ARIEvent
from voxtra.ari.models import Channel
from voxtra.config import AsteriskConfig
from voxtra.events import (
    CallEndedEvent,
    CallStartedEvent,
    DTMFEvent,
    EventType,
)
from voxtra.registry import registry
from voxtra.telephony.asterisk import AsteriskAdapter, AsteriskARIAdapter


class TestAdapterConstruction:
    def test_explicit_kwargs(self) -> None:
        adapter = AsteriskAdapter(
            ari_url="http://pbx:8088",
            ari_user="admin",
            ari_password="secret",
            app_name="tenant-acme",
        )
        assert adapter.app_name == "tenant-acme"
        assert adapter.client.app_name == "tenant-acme"
        assert adapter.is_connected is False

    def test_from_config(self) -> None:
        cfg = AsteriskConfig(
            base_url="http://pbx:8088",
            username="admin",
            password="secret",
            app_name="tenant-acme",
        )
        adapter = AsteriskAdapter.from_config(cfg)
        assert adapter.app_name == "tenant-acme"

    def test_alias(self) -> None:
        # The legacy class name still works.
        assert AsteriskARIAdapter is AsteriskAdapter

    def test_registered_with_registry(self) -> None:
        # The decorator registers the adapter at import time.
        cls = registry.resolve_telephony("asterisk")
        assert cls is AsteriskARIAdapter


class TestEventTranslation:
    def setup_method(self) -> None:
        self.adapter = AsteriskAdapter(
            ari_url="http://pbx:8088",
            ari_user="u",
            ari_password="p",
        )

    def test_stasis_start_becomes_call_started(self) -> None:
        ari_event = ARIEvent(
            type="StasisStart",
            application="voxtra",
            channel=Channel(
                id="ch-001",
                caller_number="+265888111111",
                dialplan_exten="1000",
            ),
        )
        out = self.adapter.translate_event(ari_event)
        assert isinstance(out, CallStartedEvent)
        assert out.session_id == "ch-001"
        assert out.caller_id == "+265888111111"
        assert out.callee_id == "1000"
        assert out.direction == "inbound"
        assert out.data["channel_id"] == "ch-001"

    def test_stasis_end_becomes_call_ended(self) -> None:
        ari_event = ARIEvent(type="StasisEnd", channel=Channel(id="ch-002"))
        out = self.adapter.translate_event(ari_event)
        assert isinstance(out, CallEndedEvent)
        assert out.session_id == "ch-002"
        assert out.reason == "stasis_end"

    def test_dtmf_received(self) -> None:
        ari_event = ARIEvent(
            type="ChannelDtmfReceived",
            channel=Channel(id="ch-003"),
            digit="7",
        )
        out = self.adapter.translate_event(ari_event)
        assert isinstance(out, DTMFEvent)
        assert out.session_id == "ch-003"
        assert out.digit == "7"

    @pytest.mark.parametrize("ari_type", ["ChannelHangupRequest", "ChannelDestroyed"])
    def test_hangup_variants_become_call_ended(self, ari_type: str) -> None:
        ari_event = ARIEvent(
            type=ari_type,
            channel=Channel(id="ch-004"),
            cause_txt="Normal Clearing",
        )
        out = self.adapter.translate_event(ari_event)
        assert isinstance(out, CallEndedEvent)
        assert out.reason == "Normal Clearing"

    def test_unknown_event_returns_none(self) -> None:
        ari_event = ARIEvent(type="ChannelTalkingFinished", channel=Channel(id="x"))
        assert self.adapter.translate_event(ari_event) is None

    def test_event_without_channel_returns_none(self) -> None:
        ari_event = ARIEvent(type="StasisStart", channel=None)
        assert self.adapter.translate_event(ari_event) is None

    def test_translate_uses_event_type_enum(self) -> None:
        ari_event = ARIEvent(
            type="StasisStart",
            channel=Channel(id="ch-005", caller_number="+1", dialplan_exten="2000"),
        )
        out = self.adapter.translate_event(ari_event)
        assert out is not None
        assert out.type == EventType.CALL_STARTED
