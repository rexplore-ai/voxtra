"""Tests for Voxtra ARI client models and event parsing."""

from __future__ import annotations

from voxtra.ari.events import parse_ari_event
from voxtra.ari.models import Bridge, Channel, Playback


class TestChannel:
    def test_from_ari_minimal(self) -> None:
        ch = Channel.from_ari({"id": "ch-1", "name": "PJSIP/trunk-001"})
        assert ch.id == "ch-1"
        assert ch.name == "PJSIP/trunk-001"

    def test_from_ari_full(self) -> None:
        data = {
            "id": "ch-abc",
            "name": "PJSIP/trunk-001",
            "state": "Up",
            "caller": {"number": "+265888111111", "name": "John"},
            "connected": {"number": "1000", "name": "Support"},
            "dialplan": {"context": "from-carrier", "exten": "1000", "priority": 1},
            "language": "en",
            "accountcode": "acme",
            "creationtime": "2025-01-01T00:00:00Z",
        }
        ch = Channel.from_ari(data)
        assert ch.id == "ch-abc"
        assert ch.caller_number == "+265888111111"
        assert ch.caller_name == "John"
        assert ch.connected_number == "1000"
        assert ch.dialplan_context == "from-carrier"
        assert ch.dialplan_exten == "1000"
        assert ch.dialplan_priority == 1

    def test_from_ari_empty(self) -> None:
        ch = Channel.from_ari({})
        assert ch.id == ""
        assert ch.state == ""


class TestBridge:
    def test_from_ari(self) -> None:
        data = {
            "id": "br-1",
            "technology": "simple_bridge",
            "bridge_type": "mixing",
            "channels": ["ch-1", "ch-2"],
        }
        br = Bridge.from_ari(data)
        assert br.id == "br-1"
        assert br.bridge_type == "mixing"
        assert br.channels == ["ch-1", "ch-2"]


class TestPlayback:
    def test_from_ari(self) -> None:
        data = {
            "id": "pb-1",
            "media_uri": "sound:hello-world",
            "target_uri": "channel:ch-1",
            "state": "playing",
        }
        pb = Playback.from_ari(data)
        assert pb.id == "pb-1"
        assert pb.media_uri == "sound:hello-world"
        assert pb.state == "playing"


class TestParseARIEvent:
    def test_stasis_start(self) -> None:
        raw = {
            "type": "StasisStart",
            "application": "voxtra",
            "timestamp": "2025-01-01T00:00:00Z",
            "channel": {
                "id": "ch-1",
                "name": "PJSIP/trunk-001",
                "state": "Ring",
                "caller": {"number": "+265888111111", "name": ""},
                "dialplan": {"context": "inbound", "exten": "1000", "priority": 1},
            },
        }
        event = parse_ari_event(raw)
        assert event.type == "StasisStart"
        assert event.application == "voxtra"
        assert event.channel is not None
        assert event.channel.id == "ch-1"
        assert event.channel.caller_number == "+265888111111"
        assert event.channel.dialplan_exten == "1000"

    def test_dtmf_received(self) -> None:
        raw = {
            "type": "ChannelDtmfReceived",
            "application": "voxtra",
            "digit": "5",
            "channel": {"id": "ch-1", "name": "PJSIP/trunk-001"},
        }
        event = parse_ari_event(raw)
        assert event.type == "ChannelDtmfReceived"
        assert event.digit == "5"
        assert event.channel is not None

    def test_stasis_end(self) -> None:
        raw = {
            "type": "StasisEnd",
            "application": "voxtra",
            "channel": {"id": "ch-1"},
        }
        event = parse_ari_event(raw)
        assert event.type == "StasisEnd"
        assert event.channel is not None
        assert event.channel.id == "ch-1"

    def test_no_channel(self) -> None:
        raw = {"type": "PlaybackFinished", "playback": {"id": "pb-1"}}
        event = parse_ari_event(raw)
        assert event.type == "PlaybackFinished"
        assert event.channel is None
        assert event.playback_id == "pb-1"

    def test_raw_preserved(self) -> None:
        raw = {"type": "Custom", "extra_field": "value"}
        event = parse_ari_event(raw)
        assert event.raw["extra_field"] == "value"
