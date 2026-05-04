"""Tests for Voxtra AudioSocket server and codec helpers."""

from __future__ import annotations

import asyncio
import struct

import pytest

from voxtra.audio.codec import (
    alaw_to_pcm,
    convert_audio,
    pcm_to_alaw,
    pcm_to_ulaw,
    ulaw_to_pcm,
)
from voxtra.audio.socket import (
    FRAME_AUDIO,
    FRAME_HANGUP,
    FRAME_UUID,
    AudioSocketServer,
)
from voxtra.types import AudioCodec


class TestAudioSocketServer:
    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        server = AudioSocketServer(host="127.0.0.1", port=0)
        port = await server.start()
        assert port > 0
        assert server.is_running
        await server.stop()
        assert not server.is_running

    @pytest.mark.asyncio
    async def test_accept_connection(self) -> None:
        server = AudioSocketServer(host="127.0.0.1", port=0)
        port = await server.start()

        # Simulate Asterisk connecting
        async def fake_asterisk():
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            # Send a UUID frame
            uuid_bytes = bytes(16)
            length = struct.pack(">I", len(uuid_bytes))[1:]
            writer.write(bytes([FRAME_UUID]) + length + uuid_bytes)
            await writer.drain()
            # Send hangup
            writer.write(bytes([FRAME_HANGUP]) + b"\x00\x00\x00")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        asyncio.create_task(fake_asterisk())

        conn = await server.accept(timeout=5.0)
        assert conn is not None
        assert not conn.is_closed

        # Read the frames
        chunks = []
        async for chunk in conn.receive():
            chunks.append(chunk)

        # Should get no audio chunks (only UUID + hangup)
        assert len(chunks) == 0
        assert conn.is_closed

        await server.stop()

    @pytest.mark.asyncio
    async def test_receive_audio_frames(self) -> None:
        server = AudioSocketServer(host="127.0.0.1", port=0)
        port = await server.start()

        audio_data = b"\x7f" * 160  # 160 bytes of ulaw audio

        async def fake_asterisk():
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            # Send audio frame
            length = struct.pack(">I", len(audio_data))[1:]
            writer.write(bytes([FRAME_AUDIO]) + length + audio_data)
            await writer.drain()
            # Send hangup to close
            writer.write(bytes([FRAME_HANGUP]) + b"\x00\x00\x00")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        asyncio.create_task(fake_asterisk())

        conn = await server.accept(timeout=5.0)
        chunks = []
        async for chunk in conn.receive():
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].data == audio_data
        assert chunks[0].codec == AudioCodec.ULAW

        await server.stop()

    @pytest.mark.asyncio
    async def test_accept_timeout(self) -> None:
        server = AudioSocketServer(host="127.0.0.1", port=0)
        await server.start()

        with pytest.raises(TimeoutError):
            await server.accept(timeout=0.1)

        await server.stop()


class TestCodecConversion:
    def test_ulaw_to_pcm_length(self) -> None:
        ulaw = bytes([0xFF] * 10)
        pcm = ulaw_to_pcm(ulaw)
        assert len(pcm) == 20  # 10 samples * 2 bytes

    def test_pcm_to_ulaw_length(self) -> None:
        pcm = b"\x00\x00" * 10
        ulaw = pcm_to_ulaw(pcm)
        assert len(ulaw) == 10

    def test_ulaw_roundtrip_silence(self) -> None:
        # ulaw silence (0xFF) -> PCM -> back to ulaw
        ulaw_orig = bytes([0xFF] * 100)
        pcm = ulaw_to_pcm(ulaw_orig)
        ulaw_back = pcm_to_ulaw(pcm)
        assert len(ulaw_back) == 100

    def test_alaw_to_pcm_length(self) -> None:
        alaw = bytes([0xD5] * 10)
        pcm = alaw_to_pcm(alaw)
        assert len(pcm) == 20

    def test_pcm_to_alaw_length(self) -> None:
        pcm = b"\x00\x00" * 10
        alaw = pcm_to_alaw(pcm)
        assert len(alaw) == 10

    def test_convert_same_codec_noop(self) -> None:
        data = b"\x80" * 50
        result = convert_audio(data, from_codec=AudioCodec.ULAW, to_codec=AudioCodec.ULAW)
        assert result == data

    def test_convert_unsupported_raises(self) -> None:
        from voxtra.exceptions import CodecError
        with pytest.raises(CodecError):
            convert_audio(b"\x00", from_codec=AudioCodec.OPUS, to_codec=AudioCodec.PCM_S16LE)
