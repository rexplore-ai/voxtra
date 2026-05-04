"""Asterisk ARI adapter for Voxtra.

Wraps :class:`voxtra.ari.client.ARIClient` so it conforms to the
:class:`BaseTelephonyAdapter` interface used by :class:`VoxtraApp`. The
adapter is the boundary at which raw ARI events are translated into
:class:`VoxtraEvent` objects; everything above it is backend-agnostic.
"""

from __future__ import annotations

import logging
from typing import Any

from voxtra.ari.client import ARIClient
from voxtra.ari.events import ARIEvent
from voxtra.config import AsteriskConfig
from voxtra.events import (
    CallEndedEvent,
    CallStartedEvent,
    DTMFEvent,
    VoxtraEvent,
)
from voxtra.exceptions import TelephonyConnectionError, TelephonyError
from voxtra.registry import registry
from voxtra.telephony.base import BaseTelephonyAdapter, EventCallback

logger = logging.getLogger("voxtra.telephony.asterisk")


@registry.register_telephony("asterisk")
class AsteriskARIAdapter(BaseTelephonyAdapter):
    """Asterisk ARI telephony adapter.

    Constructed either from explicit ARI parameters or from an
    :class:`AsteriskConfig`::

        adapter = AsteriskARIAdapter(
            ari_url="http://pbx:8088",
            ari_user="asterisk",
            ari_password="secret",
            app_name="voxtra",
        )
        # or
        adapter = AsteriskARIAdapter.from_config(asterisk_config)

    The underlying :class:`ARIClient` is exposed as :attr:`client` for
    components (notably :class:`CallSession`) that need direct ARI
    access for operations not covered by the abstract interface
    (bridges, externalMedia, recordings, etc.).
    """

    def __init__(
        self,
        ari_url: str = "",
        ari_user: str = "",
        ari_password: str = "",
        *,
        app_name: str = "voxtra",
        reconnect_interval: float = 5.0,
        client: ARIClient | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            self.app_name = client.app_name
        else:
            self._client = ARIClient(
                base_url=ari_url,
                username=ari_user,
                password=ari_password,
                app_name=app_name,
                reconnect_interval=reconnect_interval,
            )
            self.app_name = app_name

        self._connected = False
        self._listening = False

    @classmethod
    def from_config(cls, config: AsteriskConfig) -> AsteriskARIAdapter:
        """Build an adapter from an :class:`AsteriskConfig`."""
        return cls(
            ari_url=config.base_url,
            ari_user=config.username,
            ari_password=config.password,
            app_name=config.app_name,
        )

    @property
    def client(self) -> ARIClient:
        """The underlying :class:`ARIClient`."""
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        try:
            await self._client.connect()
        except Exception as exc:
            raise TelephonyConnectionError(
                f"Failed to connect to Asterisk ARI at {self._client.base_url}: {exc}"
            ) from exc
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        self._listening = False
        try:
            await self._client.close()
        except Exception:
            logger.exception("Error closing ARI client")

    # ------------------------------------------------------------------
    # Event listening
    # ------------------------------------------------------------------

    async def listen(self, callback: EventCallback) -> None:
        """Iterate ARI events and dispatch translated VoxtraEvents.

        Blocks until the underlying ARI WebSocket closes or
        :meth:`disconnect` is called.
        """
        self._listening = True
        try:
            async for ari_event in self._client.events():
                if not self._listening:
                    break
                voxtra_event = self.translate_event(ari_event)
                if voxtra_event is None:
                    continue
                try:
                    await callback(voxtra_event)
                except Exception:
                    logger.exception(
                        "Error in event callback for %s", voxtra_event.type
                    )
        except Exception as exc:
            if self._listening:
                logger.error("ARI event stream error: %s", exc)
                raise TelephonyError(f"ARI event stream error: {exc}") from exc

    # ------------------------------------------------------------------
    # Call control (BaseTelephonyAdapter contract)
    # ------------------------------------------------------------------

    async def answer_call(self, channel_id: str) -> None:
        await self._client.answer_channel(channel_id)

    async def hangup_call(self, channel_id: str) -> None:
        await self._client.hangup_channel(channel_id)

    async def transfer_call(self, channel_id: str, target: str) -> None:
        await self._client.redirect_channel(channel_id, f"PJSIP/{target}")

    async def hold_call(self, channel_id: str) -> None:
        await self._client.moh_start(channel_id)

    async def send_dtmf(self, channel_id: str, digits: str) -> None:
        await self._client.send_dtmf(channel_id, digits)

    async def create_media_bridge(self, channel_id: str) -> str:
        """Create a mixing bridge with externalMedia and add the channel.

        Returns the externalMedia channel id; callers can use it to
        wire up audio I/O. For AudioSocket-based flows
        :meth:`CallSession.open_audio_socket` is preferred.
        """
        bridge = await self._client.create_bridge(bridge_type="mixing")
        await self._client.add_to_bridge(bridge.id, [channel_id])
        return bridge.id

    async def play_audio(self, channel_id: str, audio_uri: str) -> None:
        await self._client.play_on_channel(channel_id, audio_uri)

    # ------------------------------------------------------------------
    # Outbound (extra over BaseTelephonyAdapter)
    # ------------------------------------------------------------------

    async def originate(
        self,
        endpoint: str,
        *,
        caller_id: str = "",
        timeout: int = 30,
        variables: dict[str, str] | None = None,
    ) -> str:
        """Originate an outbound call. Returns the channel id."""
        channel = await self._client.originate(
            endpoint,
            caller_id=caller_id,
            timeout=timeout,
            variables=variables,
        )
        return channel.id

    # ------------------------------------------------------------------
    # Event translation
    # ------------------------------------------------------------------

    def translate_event(self, event: ARIEvent) -> VoxtraEvent | None:
        """Translate an :class:`ARIEvent` into a :class:`VoxtraEvent`.

        Returns ``None`` for ARI event types that have no Voxtra-level
        meaning (so callers can simply ``continue``).
        """
        channel = event.channel
        if channel is None:
            return None

        channel_id = channel.id
        session_id = channel_id

        if event.type == "StasisStart":
            return CallStartedEvent(
                session_id=session_id,
                caller_id=channel.caller_number,
                callee_id=channel.dialplan_exten,
                direction="inbound",
                data={"channel_id": channel_id},
            )

        if event.type == "StasisEnd":
            return CallEndedEvent(
                session_id=session_id,
                reason="stasis_end",
                data={"channel_id": channel_id},
            )

        if event.type == "ChannelDtmfReceived":
            return DTMFEvent(
                session_id=session_id,
                digit=event.digit or "",
                data={"channel_id": channel_id},
            )

        if event.type in ("ChannelHangupRequest", "ChannelDestroyed"):
            return CallEndedEvent(
                session_id=session_id,
                reason=event.cause_txt or event.type,
                data={"channel_id": channel_id},
            )

        return None

    # Keep this hook available to subclasses but do not use directly.
    def _translate_event(self, raw: dict[str, Any]) -> VoxtraEvent | None:  # pragma: no cover
        return self.translate_event(ARIEvent.model_validate(raw))


# Public alias — the cleaner short name new code should use.
AsteriskAdapter = AsteriskARIAdapter
