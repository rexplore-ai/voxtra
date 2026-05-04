"""Tests for CallSessionMediaTransport — the bridge between the
AudioSocket/AudioChunk stack and the MediaTransport/AudioFrame stack."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from voxtra.media.audio import AudioFrame
from voxtra.media.session_transport import CallSessionMediaTransport
from voxtra.session import CallSession
from voxtra.types import AudioChunk, AudioCodec


class _FakeAudioConn:
    def __init__(self, codec: AudioCodec = AudioCodec.ULAW) -> None:
        self.codec = codec
        self.sent: list[AudioChunk] = []

    async def send(self, chunk: AudioChunk) -> None:
        self.sent.append(chunk)


def _attach_fake_conn(session: CallSession, codec: AudioCodec = AudioCodec.ULAW) -> _FakeAudioConn:
    conn = _FakeAudioConn(codec=codec)
    session._audio_conn = conn  # type: ignore[assignment]
    return conn


class TestFromChunkAndToChunk:
    def test_from_chunk_copies_fields(self) -> None:
        chunk = AudioChunk(
            data=b"\xff\xff",
            sample_rate=16000,
            channels=2,
            codec=AudioCodec.PCM_S16LE,
            duration_ms=10.0,
            sequence=42,
        )
        frame = AudioFrame.from_chunk(chunk)
        assert frame.data == chunk.data
        assert frame.sample_rate == 16000
        assert frame.channels == 2
        assert frame.codec == AudioCodec.PCM_S16LE
        assert frame.sequence == 42

    def test_to_chunk_round_trip(self) -> None:
        original = AudioChunk(
            data=b"\x01\x02\x03",
            sample_rate=8000,
            codec=AudioCodec.ULAW,
            sequence=7,
        )
        round_tripped = AudioFrame.from_chunk(original).to_chunk()
        assert round_tripped == original


class TestToCodec:
    def test_to_codec_noop_when_already_target(self) -> None:
        frame = AudioFrame(data=b"\x80" * 10, codec=AudioCodec.ULAW)
        assert frame.to_codec(AudioCodec.ULAW) is frame

    def test_to_codec_ulaw_to_pcm(self) -> None:
        frame = AudioFrame(data=b"\xff" * 10, codec=AudioCodec.ULAW)
        pcm = frame.to_codec(AudioCodec.PCM_S16LE)
        assert pcm.codec == AudioCodec.PCM_S16LE
        # μ-law silence (0xFF) → 10 samples × 2 bytes/sample = 20 bytes
        assert len(pcm.data) == 20


class TestCallSessionMediaTransportReceive:
    @pytest.mark.asyncio
    async def test_receive_yields_frames_in_target_codec(self) -> None:
        session = CallSession(channel_id="ch-rx-001")

        async def fake_audio_stream() -> AsyncIterator[AudioChunk]:
            yield AudioChunk(data=b"\xff" * 10, codec=AudioCodec.ULAW, sequence=0)
            yield AudioChunk(data=b"\xff" * 10, codec=AudioCodec.ULAW, sequence=1)

        session.audio_stream = fake_audio_stream  # type: ignore[method-assign,assignment]

        transport = CallSessionMediaTransport(session, target_codec=AudioCodec.PCM_S16LE)
        frames = [f async for f in transport.receive_audio()]
        assert len(frames) == 2
        assert all(f.codec == AudioCodec.PCM_S16LE for f in frames)
        assert all(len(f.data) == 20 for f in frames)
        assert frames[0].sequence == 0
        assert frames[1].sequence == 1

    @pytest.mark.asyncio
    async def test_receive_passthrough_when_codecs_match(self) -> None:
        session = CallSession(channel_id="ch-rx-002")
        chunk = AudioChunk(data=b"\x01\x02\x03", codec=AudioCodec.ULAW)

        async def fake_audio_stream() -> AsyncIterator[AudioChunk]:
            yield chunk

        session.audio_stream = fake_audio_stream  # type: ignore[method-assign,assignment]

        transport = CallSessionMediaTransport(session, target_codec=AudioCodec.ULAW)
        frames = [f async for f in transport.receive_audio()]
        assert len(frames) == 1
        # Same bytes, no conversion.
        assert frames[0].data == b"\x01\x02\x03"
        assert frames[0].codec == AudioCodec.ULAW


class TestCallSessionMediaTransportSend:
    @pytest.mark.asyncio
    async def test_send_transcodes_to_session_codec(self) -> None:
        session = CallSession(channel_id="ch-tx-001")
        conn = _attach_fake_conn(session, codec=AudioCodec.ULAW)
        transport = CallSessionMediaTransport(session)

        # Send a PCM frame; the session expects μ-law.
        pcm_frame = AudioFrame(data=b"\x00\x00" * 10, codec=AudioCodec.PCM_S16LE)
        await transport.send_audio(pcm_frame)

        assert len(conn.sent) == 1
        assert conn.sent[0].codec == AudioCodec.ULAW
        # PCM → μ-law: 10 samples → 10 bytes.
        assert len(conn.sent[0].data) == 10

    @pytest.mark.asyncio
    async def test_send_passthrough_when_codecs_match(self) -> None:
        session = CallSession(channel_id="ch-tx-002")
        conn = _attach_fake_conn(session, codec=AudioCodec.ULAW)
        transport = CallSessionMediaTransport(session)

        ulaw_frame = AudioFrame(data=b"\xff" * 5, codec=AudioCodec.ULAW)
        await transport.send_audio(ulaw_frame)

        assert conn.sent[0].data == b"\xff" * 5


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_connect_disconnect_are_noops(self) -> None:
        session = CallSession(channel_id="ch-life-001")
        transport = CallSessionMediaTransport(session)
        await transport.connect()
        await transport.disconnect()  # neither raises

    def test_is_connected_tracks_session_state(self) -> None:
        session = CallSession(channel_id="ch-life-002")
        transport = CallSessionMediaTransport(session)
        assert transport.is_connected is True

        session._hangup_dispatched = True
        assert transport.is_connected is False
