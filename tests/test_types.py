"""Tests for Voxtra types — AudioChunk, SIPTrunk, enums."""

from __future__ import annotations

from voxtra.types import (
    AudioChunk,
    AudioCodec,
    CallDirection,
    CallState,
    MediaTransportType,
    SIPTrunk,
)


class TestAudioChunk:
    def test_defaults(self) -> None:
        chunk = AudioChunk()
        assert chunk.data == b""
        assert chunk.sample_rate == 8000
        assert chunk.channels == 1
        assert chunk.codec == AudioCodec.ULAW
        assert chunk.is_empty is True
        assert chunk.n_samples == 0

    def test_with_ulaw_data(self) -> None:
        data = b"\x7f" * 160
        chunk = AudioChunk(data=data)
        assert chunk.is_empty is False
        assert chunk.n_samples == 160  # 1 byte per sample for ulaw

    def test_with_pcm_data(self) -> None:
        data = b"\x00\x01" * 160  # 320 bytes = 160 samples
        chunk = AudioChunk(data=data, codec=AudioCodec.PCM_S16LE)
        assert chunk.n_samples == 160  # 2 bytes per sample


class TestSIPTrunk:
    def test_defaults(self) -> None:
        trunk = SIPTrunk(host="sip.carrier.com")
        assert trunk.port == 5060
        assert trunk.transport == "udp"
        assert trunk.codecs == ["ulaw", "alaw"]
        assert trunk.realm == "sip.carrier.com"  # auto-set from host

    def test_explicit_realm(self) -> None:
        trunk = SIPTrunk(host="sip.carrier.com", realm="custom.realm")
        assert trunk.realm == "custom.realm"

    def test_did(self) -> None:
        trunk = SIPTrunk(host="sip.x.com", did="+265999123456")
        assert trunk.did == "+265999123456"


class TestEnums:
    def test_call_direction(self) -> None:
        assert CallDirection.INBOUND == "inbound"
        assert CallDirection.OUTBOUND == "outbound"

    def test_call_state(self) -> None:
        assert CallState.RINGING == "ringing"
        assert CallState.COMPLETED == "completed"

    def test_media_transport_type(self) -> None:
        assert MediaTransportType.AUDIOSOCKET == "audiosocket"
        assert MediaTransportType.WEBSOCKET == "websocket"

    def test_audio_codec(self) -> None:
        assert AudioCodec.ULAW == "ulaw"
        assert AudioCodec.ALAW == "alaw"
        assert AudioCodec.PCM_S16LE == "pcm_s16le"
