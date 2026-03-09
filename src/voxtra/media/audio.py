"""Audio frame and codec handling for Voxtra.

AudioFrame is the fundamental unit of audio data flowing through
the Voxtra pipeline. This module also provides codec conversion
utilities for telephony audio formats.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from voxtra.types import AudioCodec


class AudioFrame(BaseModel):
    """A single frame of audio data.

    AudioFrame is the universal audio container in Voxtra. All
    components — media transports, STT, TTS, VAD — communicate
    using AudioFrame objects.

    Attributes:
        data: Raw audio bytes.
        sample_rate: Sample rate in Hz (default 8000 for telephony).
        channels: Number of audio channels (1 = mono).
        codec: Audio codec of the data.
        timestamp_ms: Timestamp in milliseconds relative to stream start.
        duration_ms: Duration of this frame in milliseconds.
        sequence: Frame sequence number for ordering.
    """

    data: bytes = b""
    sample_rate: int = 8000
    channels: int = 1
    codec: AudioCodec = AudioCodec.PCM_S16LE
    timestamp_ms: float = 0.0
    duration_ms: float = 20.0
    sequence: int = 0

    model_config = {"arbitrary_types_allowed": True}

    @property
    def n_samples(self) -> int:
        """Number of audio samples in this frame."""
        bytes_per_sample = 2  # 16-bit
        return len(self.data) // (bytes_per_sample * self.channels)

    @property
    def is_empty(self) -> bool:
        """Check if this frame contains audio data."""
        return len(self.data) == 0

    def to_pcm_s16le(self) -> AudioFrame:
        """Convert this frame to 16-bit signed little-endian PCM.

        If the frame is already in PCM_S16LE format, returns self.
        Otherwise, performs codec conversion.
        """
        if self.codec == AudioCodec.PCM_S16LE:
            return self

        converted = convert_audio(
            self.data,
            from_codec=self.codec,
            to_codec=AudioCodec.PCM_S16LE,
        )
        return AudioFrame(
            data=converted,
            sample_rate=self.sample_rate,
            channels=self.channels,
            codec=AudioCodec.PCM_S16LE,
            timestamp_ms=self.timestamp_ms,
            duration_ms=self.duration_ms,
            sequence=self.sequence,
        )


class SilenceFrame(AudioFrame):
    """A frame of silence (all zeros).

    Used for padding, hold audio, and silence insertion.
    """

    def __init__(self, duration_ms: float = 20.0, sample_rate: int = 8000, **kwargs: Any) -> None:
        n_samples = int(sample_rate * duration_ms / 1000)
        silence_data = b"\x00" * (n_samples * 2)  # 16-bit = 2 bytes per sample
        super().__init__(
            data=silence_data,
            sample_rate=sample_rate,
            channels=1,
            codec=AudioCodec.PCM_S16LE,
            duration_ms=duration_ms,
            **kwargs,
        )


def convert_audio(
    data: bytes,
    *,
    from_codec: AudioCodec,
    to_codec: AudioCodec,
) -> bytes:
    """Convert audio data between codecs.

    Currently supports:
    - ULAW <-> PCM_S16LE
    - ALAW <-> PCM_S16LE

    Args:
        data: Raw audio bytes in the source codec.
        from_codec: Source codec.
        to_codec: Target codec.

    Returns:
        Converted audio bytes.

    Raises:
        CodecError: If the conversion is not supported.
    """
    from voxtra.exceptions import CodecError

    if from_codec == to_codec:
        return data

    # ULAW -> PCM
    if from_codec == AudioCodec.ULAW and to_codec == AudioCodec.PCM_S16LE:
        return _ulaw_to_pcm(data)

    # PCM -> ULAW
    if from_codec == AudioCodec.PCM_S16LE and to_codec == AudioCodec.ULAW:
        return _pcm_to_ulaw(data)

    # ALAW -> PCM
    if from_codec == AudioCodec.ALAW and to_codec == AudioCodec.PCM_S16LE:
        return _alaw_to_pcm(data)

    # PCM -> ALAW
    if from_codec == AudioCodec.PCM_S16LE and to_codec == AudioCodec.ALAW:
        return _pcm_to_alaw(data)

    raise CodecError(f"Unsupported codec conversion: {from_codec} -> {to_codec}")


# ---------------------------------------------------------------------------
# μ-law codec (ITU-T G.711)
# ---------------------------------------------------------------------------

# μ-law decompression table
_ULAW_DECOMPRESS_TABLE = [
    -32124, -31100, -30076, -29052, -28028, -27004, -25980, -24956,
    -23932, -22908, -21884, -20860, -19836, -18812, -17788, -16764,
    -15996, -15484, -14972, -14460, -13948, -13436, -12924, -12412,
    -11900, -11388, -10876, -10364, -9852, -9340, -8828, -8316,
    -7932, -7676, -7420, -7164, -6908, -6652, -6396, -6140,
    -5884, -5628, -5372, -5116, -4860, -4604, -4348, -4092,
    -3900, -3772, -3644, -3516, -3388, -3260, -3132, -3004,
    -2876, -2748, -2620, -2492, -2364, -2236, -2108, -1980,
    -1884, -1820, -1756, -1692, -1628, -1564, -1500, -1436,
    -1372, -1308, -1244, -1180, -1116, -1052, -988, -924,
    -876, -844, -812, -780, -748, -716, -684, -652,
    -620, -588, -556, -524, -492, -460, -428, -396,
    -372, -356, -340, -324, -308, -292, -276, -260,
    -244, -228, -212, -196, -180, -164, -148, -132,
    -120, -112, -104, -96, -88, -80, -72, -64,
    -56, -48, -40, -32, -24, -16, -8, 0,
    32124, 31100, 30076, 29052, 28028, 27004, 25980, 24956,
    23932, 22908, 21884, 20860, 19836, 18812, 17788, 16764,
    15996, 15484, 14972, 14460, 13948, 13436, 12924, 12412,
    11900, 11388, 10876, 10364, 9852, 9340, 8828, 8316,
    7932, 7676, 7420, 7164, 6908, 6652, 6396, 6140,
    5884, 5628, 5372, 5116, 4860, 4604, 4348, 4092,
    3900, 3772, 3644, 3516, 3388, 3260, 3132, 3004,
    2876, 2748, 2620, 2492, 2364, 2236, 2108, 1980,
    1884, 1820, 1756, 1692, 1628, 1564, 1500, 1436,
    1372, 1308, 1244, 1180, 1116, 1052, 988, 924,
    876, 844, 812, 780, 748, 716, 684, 652,
    620, 588, 556, 524, 492, 460, 428, 396,
    372, 356, 340, 324, 308, 292, 276, 260,
    244, 228, 212, 196, 180, 164, 148, 132,
    120, 112, 104, 96, 88, 80, 72, 64,
    56, 48, 40, 32, 24, 16, 8, 0,
]


def _ulaw_to_pcm(data: bytes) -> bytes:
    """Convert μ-law encoded audio to 16-bit signed PCM."""
    import struct

    pcm = bytearray(len(data) * 2)
    for i, byte in enumerate(data):
        sample = _ULAW_DECOMPRESS_TABLE[byte]
        struct.pack_into("<h", pcm, i * 2, sample)
    return bytes(pcm)


def _pcm_to_ulaw(data: bytes) -> bytes:
    """Convert 16-bit signed PCM to μ-law encoding."""
    import struct

    n_samples = len(data) // 2
    ulaw = bytearray(n_samples)

    for i in range(n_samples):
        sample = struct.unpack_from("<h", data, i * 2)[0]
        ulaw[i] = _linear_to_ulaw(sample)

    return bytes(ulaw)


def _linear_to_ulaw(sample: int) -> int:
    """Convert a single 16-bit PCM sample to μ-law."""
    bias = 0x84
    clip = 32635

    sign = (sample >> 8) & 0x80
    if sign:
        sample = -sample
    if sample > clip:
        sample = clip

    sample += bias
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1

    mantissa = (sample >> (exponent + 3)) & 0x0F
    ulaw_byte = ~(sign | (exponent << 4) | mantissa) & 0xFF
    return ulaw_byte


def _alaw_to_pcm(data: bytes) -> bytes:
    """Convert A-law encoded audio to 16-bit signed PCM."""
    import struct

    pcm = bytearray(len(data) * 2)
    for i, byte in enumerate(data):
        sample = _alaw_decode_sample(byte)
        struct.pack_into("<h", pcm, i * 2, sample)
    return bytes(pcm)


def _pcm_to_alaw(data: bytes) -> bytes:
    """Convert 16-bit signed PCM to A-law encoding."""
    import struct

    n_samples = len(data) // 2
    alaw = bytearray(n_samples)

    for i in range(n_samples):
        sample = struct.unpack_from("<h", data, i * 2)[0]
        alaw[i] = _linear_to_alaw(sample)

    return bytes(alaw)


def _alaw_decode_sample(alaw_byte: int) -> int:
    """Decode a single A-law byte to a 16-bit PCM sample."""
    alaw_byte ^= 0x55
    sign = alaw_byte & 0x80
    exponent = (alaw_byte >> 4) & 0x07
    mantissa = alaw_byte & 0x0F

    if exponent == 0:
        sample = (mantissa << 4) + 8
    else:
        sample = ((mantissa << 4) + 0x108) << (exponent - 1)

    return -sample if sign else sample


def _linear_to_alaw(sample: int) -> int:
    """Convert a single 16-bit PCM sample to A-law."""
    sign = 0
    if sample < 0:
        sign = 0x80
        sample = -sample

    if sample > 32767:
        sample = 32767

    if sample >= 256:
        exponent = 7
        mask = 0x4000
        while exponent > 1 and not (sample & mask):
            exponent -= 1
            mask >>= 1
        mantissa = (sample >> (exponent + 3)) & 0x0F
        alaw_byte = sign | (exponent << 4) | mantissa
    else:
        alaw_byte = sign | (sample >> 4)

    return alaw_byte ^ 0x55
