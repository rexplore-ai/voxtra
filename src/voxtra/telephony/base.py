"""Abstract base class for telephony adapters.

Telephony adapters connect Voxtra to PBX systems and telephony
infrastructure. They handle call lifecycle, media bridging,
and event translation from the telephony domain to Voxtra events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

from voxtra.events import VoxtraEvent

# Callback type for event dispatching
EventCallback = Callable[[VoxtraEvent], Coroutine[Any, Any, None]]


class BaseTelephonyAdapter(ABC):
    """Abstract interface for telephony adapters.

    All telephony backends (Asterisk, FreeSWITCH, LiveKit, etc.)
    must implement this interface. The adapter is responsible for:

    1. Connecting to the telephony backend
    2. Listening for incoming calls and events
    3. Translating backend-specific events to VoxtraEvents
    4. Providing call control operations (answer, hangup, transfer)
    5. Setting up media bridges for audio streaming

    Example implementation::

        class MyPBXAdapter(BaseTelephonyAdapter):
            async def connect(self):
                self._client = await connect_to_pbx(self.host)

            async def listen(self, callback):
                async for raw_event in self._client.events():
                    voxtra_event = self._translate(raw_event)
                    await callback(voxtra_event)

            async def answer_call(self, channel_id):
                await self._client.answer(channel_id)

            async def hangup_call(self, channel_id):
                await self._client.hangup(channel_id)

            async def disconnect(self):
                await self._client.close()
    """

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the telephony backend.

        This should establish the control connection
        (e.g., ARI WebSocket for Asterisk, gRPC for LiveKit).
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the telephony backend."""
        ...

    @abstractmethod
    async def listen(self, callback: EventCallback) -> None:
        """Start listening for telephony events.

        This is the main event loop. It should:
        1. Subscribe to the backend's event stream
        2. Translate raw events to VoxtraEvent objects
        3. Call the callback for each event

        Args:
            callback: Async function to call for each VoxtraEvent.
        """
        ...

    @abstractmethod
    async def answer_call(self, channel_id: str) -> None:
        """Answer an incoming call.

        Args:
            channel_id: Backend-specific channel/call identifier.
        """
        ...

    @abstractmethod
    async def hangup_call(self, channel_id: str) -> None:
        """Hang up a call.

        Args:
            channel_id: Backend-specific channel/call identifier.
        """
        ...

    @abstractmethod
    async def transfer_call(self, channel_id: str, target: str) -> None:
        """Transfer a call to another destination.

        Args:
            channel_id: Backend-specific channel/call identifier.
            target: Extension, number, or SIP URI to transfer to.
        """
        ...

    @abstractmethod
    async def hold_call(self, channel_id: str) -> None:
        """Place a call on hold.

        Args:
            channel_id: Backend-specific channel/call identifier.
        """
        ...

    @abstractmethod
    async def send_dtmf(self, channel_id: str, digits: str) -> None:
        """Send DTMF tones on a call.

        Args:
            channel_id: Backend-specific channel/call identifier.
            digits: DTMF digits to send (e.g., "1234#").
        """
        ...

    @abstractmethod
    async def create_media_bridge(self, channel_id: str) -> str:
        """Create a media bridge for audio streaming.

        Sets up the infrastructure to stream audio between the
        call and an external media endpoint (WebSocket, RTP, etc.).

        Args:
            channel_id: Backend-specific channel/call identifier.

        Returns:
            A media endpoint identifier (e.g., WebSocket URL, RTP address).
        """
        ...

    @abstractmethod
    async def play_audio(self, channel_id: str, audio_uri: str) -> None:
        """Play an audio file or URI on a call.

        Args:
            channel_id: Backend-specific channel/call identifier.
            audio_uri: URI of the audio to play.
        """
        ...

    async def __aenter__(self) -> BaseTelephonyAdapter:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
