"""Audio buffer management for Voxtra.

Manages buffering of audio frames for smooth playback and
processing. Handles jitter, reordering, and accumulation
of frames for batch processing.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator

from voxtra.media.audio import AudioFrame

logger = logging.getLogger("voxtra.media.buffer")


class AudioBuffer:
    """Thread-safe async audio frame buffer.

    Accumulates audio frames and provides them for consumption
    when enough data is available. Useful for:

    - Smoothing jitter in real-time audio streams
    - Accumulating frames for batch STT processing
    - Providing a consistent frame size to downstream consumers

    Args:
        max_duration_ms: Maximum buffer duration in milliseconds.
        min_drain_ms: Minimum accumulated duration before draining.
    """

    def __init__(
        self,
        max_duration_ms: float = 5000.0,
        min_drain_ms: float = 100.0,
    ) -> None:
        self._frames: deque[AudioFrame] = deque()
        self._total_duration_ms: float = 0.0
        self._max_duration_ms = max_duration_ms
        self._min_drain_ms = min_drain_ms
        self._lock = asyncio.Lock()
        self._data_available = asyncio.Event()
        self._closed = False

    async def push(self, frame: AudioFrame) -> None:
        """Add an audio frame to the buffer.

        If the buffer exceeds max_duration_ms, the oldest frames
        are dropped to prevent unbounded growth.
        """
        async with self._lock:
            self._frames.append(frame)
            self._total_duration_ms += frame.duration_ms

            # Evict old frames if buffer is too full
            while self._total_duration_ms > self._max_duration_ms and len(self._frames) > 1:
                evicted = self._frames.popleft()
                self._total_duration_ms -= evicted.duration_ms

            self._data_available.set()

    async def drain(self) -> list[AudioFrame]:
        """Wait for and return all buffered frames.

        Blocks until at least min_drain_ms of audio is available,
        then returns all buffered frames and clears the buffer.
        """
        while not self._closed:
            await self._data_available.wait()

            async with self._lock:
                if self._total_duration_ms >= self._min_drain_ms or self._closed:
                    frames = list(self._frames)
                    self._frames.clear()
                    self._total_duration_ms = 0.0
                    self._data_available.clear()
                    return frames

            # Not enough data yet; wait for more
            self._data_available.clear()
            await asyncio.sleep(0.01)

        return []

    async def drain_bytes(self) -> bytes:
        """Drain the buffer and concatenate all frame data."""
        frames = await self.drain()
        return b"".join(f.data for f in frames)

    async def stream(self) -> AsyncIterator[AudioFrame]:
        """Stream frames from the buffer as they become available."""
        while not self._closed:
            frames = await self.drain()
            for frame in frames:
                yield frame

    async def close(self) -> None:
        """Close the buffer and release any waiting consumers."""
        self._closed = True
        self._data_available.set()

    @property
    def duration_ms(self) -> float:
        """Current buffered duration in milliseconds."""
        return self._total_duration_ms

    @property
    def frame_count(self) -> int:
        """Number of frames currently in the buffer."""
        return len(self._frames)

    @property
    def is_empty(self) -> bool:
        """Whether the buffer is empty."""
        return len(self._frames) == 0
