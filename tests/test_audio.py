"""Tests for Voxtra audio frame and codec handling."""

from __future__ import annotations

import struct

import pytest

from voxtra.media.audio import (
    AudioFrame,
    SilenceFrame,
    convert_audio,
)
from voxtra.types import AudioCodec


class TestAudioFrame:
    def test_default_values(self) -> None:
        frame = AudioFrame()
        assert frame.data == b""
        assert frame.sample_rate == 8000
        assert frame.channels == 1
        assert frame.codec == AudioCodec.PCM_S16LE
        assert frame.is_empty is True

    def test_with_data(self) -> None:
        data = b"\x00\x01" * 160  # 160 samples = 20ms at 8kHz
        frame = AudioFrame(data=data, sample_rate=8000)
        assert frame.is_empty is False
        assert frame.n_samples == 160

    def test_to_pcm_s16le_noop(self) -> None:
        data = b"\x00\x01" * 10
        frame = AudioFrame(data=data, codec=AudioCodec.PCM_S16LE)
        converted = frame.to_pcm_s16le()
        assert converted is frame  # Same object, no conversion needed


class TestSilenceFrame:
    def test_default_silence(self) -> None:
        frame = SilenceFrame()
        assert frame.duration_ms == 20.0
        assert frame.codec == AudioCodec.PCM_S16LE
        assert all(b == 0 for b in frame.data)

    def test_custom_duration(self) -> None:
        frame = SilenceFrame(duration_ms=40.0, sample_rate=8000)
        expected_samples = int(8000 * 40 / 1000)
        expected_bytes = expected_samples * 2
        assert len(frame.data) == expected_bytes


class TestCodecConversion:
    def test_same_codec_noop(self) -> None:
        data = b"\x80" * 100
        result = convert_audio(data, from_codec=AudioCodec.ULAW, to_codec=AudioCodec.ULAW)
        assert result == data

    def test_ulaw_to_pcm_roundtrip(self) -> None:
        # Create some ulaw data (silence = 0xFF in ulaw)
        ulaw_data = bytes([0xFF] * 10)
        pcm_data = convert_audio(
            ulaw_data,
            from_codec=AudioCodec.ULAW,
            to_codec=AudioCodec.PCM_S16LE,
        )
        assert len(pcm_data) == 20  # 10 samples * 2 bytes each

    def test_pcm_to_ulaw(self) -> None:
        # Create PCM silence
        pcm_data = b"\x00\x00" * 10
        ulaw_data = convert_audio(
            pcm_data,
            from_codec=AudioCodec.PCM_S16LE,
            to_codec=AudioCodec.ULAW,
        )
        assert len(ulaw_data) == 10

    def test_alaw_to_pcm(self) -> None:
        alaw_data = bytes([0xD5] * 10)  # A-law silence
        pcm_data = convert_audio(
            alaw_data,
            from_codec=AudioCodec.ALAW,
            to_codec=AudioCodec.PCM_S16LE,
        )
        assert len(pcm_data) == 20

    def test_unsupported_conversion_raises(self) -> None:
        from voxtra.exceptions import CodecError

        with pytest.raises(CodecError):
            convert_audio(
                b"\x00",
                from_codec=AudioCodec.OPUS,
                to_codec=AudioCodec.PCM_S16LE,
            )
