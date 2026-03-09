"""Asterisk ARI adapter for Voxtra.

This adapter connects to Asterisk via the Asterisk REST Interface (ARI)
to control calls, manage media bridges, and stream events. ARI is the
official programmable interface for building custom communications
applications on Asterisk.

Architecture:
    Asterisk ARI WebSocket → events → AsteriskARIAdapter → VoxtraEvents
    AsteriskARIAdapter → REST calls → Asterisk ARI HTTP API
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

import httpx

from voxtra.config import AsteriskConfig
from voxtra.events import (
    CallEndedEvent,
    CallStartedEvent,
    DTMFEvent,
    EventType,
    VoxtraEvent,
)
from voxtra.exceptions import TelephonyConnectionError, TelephonyError
from voxtra.telephony.base import BaseTelephonyAdapter, EventCallback

logger = logging.getLogger("voxtra.telephony.asterisk")


class AsteriskARIAdapter(BaseTelephonyAdapter):
    """Asterisk ARI telephony adapter.

    Connects to Asterisk's ARI via:
    - HTTP REST API for call control operations
    - WebSocket for real-time event streaming

    This adapter translates Asterisk Stasis events into Voxtra events
    and provides call control through the ARI REST interface.

    Configuration::

        telephony:
          provider: asterisk
          asterisk:
            base_url: http://localhost:8088
            username: asterisk
            password: secret
            app_name: voxtra

    Requires the Asterisk dialplan to route calls to the Stasis app::

        [voxtra-inbound]
        exten => _X.,1,Stasis(voxtra)
        same => n,Hangup()
    """

    def __init__(self, config: AsteriskConfig) -> None:
        self.config = config
        self._http_client: httpx.AsyncClient | None = None
        self._ws: Any = None
        self._connected = False
        self._listen_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to Asterisk ARI HTTP API."""
        self._http_client = httpx.AsyncClient(
            base_url=self.config.base_url,
            auth=(self.config.username, self.config.password),
            timeout=30.0,
        )

        # Verify connectivity
        try:
            response = await self._http_client.get("/ari/asterisk/info")
            response.raise_for_status()
            info = response.json()
            logger.info(
                "Connected to Asterisk ARI (version=%s, system=%s)",
                info.get("build", {}).get("version", "unknown"),
                info.get("system", {}).get("entity_id", "unknown"),
            )
            self._connected = True
        except httpx.HTTPError as exc:
            raise TelephonyConnectionError(
                f"Failed to connect to Asterisk ARI at {self.config.base_url}: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        """Disconnect from Asterisk ARI."""
        self._connected = False

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

        logger.info("Disconnected from Asterisk ARI")

    # ------------------------------------------------------------------
    # Event listening
    # ------------------------------------------------------------------

    async def listen(self, callback: EventCallback) -> None:
        """Listen for ARI Stasis events via WebSocket.

        Connects to the ARI WebSocket endpoint and translates
        incoming Asterisk events into VoxtraEvent objects.
        """
        try:
            import websockets
        except ImportError:
            raise TelephonyError(
                "websockets is required for ARI event listening. "
                "Install with: pip install websockets"
            )

        ws_url = self.config.websocket_url
        logger.info("Connecting to ARI WebSocket: %s", ws_url)

        try:
            self._ws = await websockets.connect(
                ws_url,
                additional_headers={
                    "Authorization": self._basic_auth_header(),
                },
            )
        except Exception as exc:
            raise TelephonyConnectionError(
                f"Failed to connect to ARI WebSocket: {exc}"
            ) from exc

        logger.info("ARI WebSocket connected. Listening for events...")

        try:
            async for message in self._ws:
                if not self._connected:
                    break

                try:
                    raw_event = json.loads(message)
                    voxtra_event = self._translate_event(raw_event)
                    if voxtra_event is not None:
                        await callback(voxtra_event)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON ARI message: %s", message[:100])
                except Exception as exc:
                    logger.error("Error processing ARI event: %s", exc)

        except Exception as exc:
            if self._connected:
                logger.error("ARI WebSocket error: %s", exc)
                raise TelephonyError(f"ARI WebSocket error: {exc}") from exc

    # ------------------------------------------------------------------
    # Call control operations
    # ------------------------------------------------------------------

    async def answer_call(self, channel_id: str) -> None:
        """Answer a ringing channel via ARI."""
        await self._ari_post(f"/ari/channels/{channel_id}/answer")
        logger.info("Answered channel %s", channel_id)

    async def hangup_call(self, channel_id: str) -> None:
        """Hang up a channel via ARI."""
        await self._ari_delete(f"/ari/channels/{channel_id}")
        logger.info("Hung up channel %s", channel_id)

    async def transfer_call(self, channel_id: str, target: str) -> None:
        """Transfer a call by redirecting the channel.

        Uses ARI channel redirect to move the call to a new
        extension in the dialplan.
        """
        await self._ari_post(
            f"/ari/channels/{channel_id}/redirect",
            params={"endpoint": f"PJSIP/{target}"},
        )
        logger.info("Transferred channel %s to %s", channel_id, target)

    async def hold_call(self, channel_id: str) -> None:
        """Place a channel on hold via ARI MOH."""
        await self._ari_post(
            f"/ari/channels/{channel_id}/moh",
            params={"mohClass": "default"},
        )
        logger.info("Placed channel %s on hold", channel_id)

    async def send_dtmf(self, channel_id: str, digits: str) -> None:
        """Send DTMF digits on a channel."""
        await self._ari_post(
            f"/ari/channels/{channel_id}/dtmf",
            params={"dtmf": digits},
        )

    async def create_media_bridge(self, channel_id: str) -> str:
        """Create a bridge with an external media channel.

        This sets up:
        1. A mixing bridge
        2. An external media channel (for audio I/O)
        3. Adds both the call channel and external media to the bridge

        Returns:
            The external media connection endpoint (e.g., WS URL).
        """
        # 1. Create a mixing bridge
        bridge_id = uuid4().hex[:12]
        bridge_resp = await self._ari_post(
            "/ari/bridges",
            params={
                "type": "mixing",
                "bridgeId": bridge_id,
                "name": f"voxtra-{bridge_id}",
            },
        )

        # 2. Create an external media channel
        external_host = "localhost:8089"  # Voxtra media server
        ext_resp = await self._ari_post(
            "/ari/channels/externalMedia",
            params={
                "app": self.config.app_name,
                "external_host": external_host,
                "format": "ulaw",
                "encapsulation": "rtp",
                "transport": "udp",
            },
        )
        ext_channel_id = ext_resp.get("id", "")

        # 3. Add both channels to the bridge
        await self._ari_post(
            f"/ari/bridges/{bridge_id}/addChannel",
            params={"channel": f"{channel_id},{ext_channel_id}"},
        )

        logger.info(
            "Created media bridge %s with external media %s for channel %s",
            bridge_id,
            ext_channel_id,
            channel_id,
        )

        return external_host

    async def play_audio(self, channel_id: str, audio_uri: str) -> None:
        """Play audio on a channel via ARI.

        Args:
            channel_id: The channel to play audio on.
            audio_uri: URI like "sound:hello-world" or "recording:abc".
        """
        await self._ari_post(
            f"/ari/channels/{channel_id}/play",
            params={"media": audio_uri},
        )

    # ------------------------------------------------------------------
    # ARI HTTP helpers
    # ------------------------------------------------------------------

    async def _ari_post(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a POST request to the ARI REST API."""
        if self._http_client is None:
            raise TelephonyError("Not connected to Asterisk ARI")

        try:
            response = await self._http_client.post(path, params=params)
            response.raise_for_status()
            if response.content:
                return response.json()
            return {}
        except httpx.HTTPStatusError as exc:
            raise TelephonyError(
                f"ARI request failed: {exc.response.status_code} {exc.response.text}"
            ) from exc

    async def _ari_delete(self, path: str, params: dict[str, Any] | None = None) -> None:
        """Make a DELETE request to the ARI REST API."""
        if self._http_client is None:
            raise TelephonyError("Not connected to Asterisk ARI")

        try:
            response = await self._http_client.delete(path, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TelephonyError(
                f"ARI request failed: {exc.response.status_code} {exc.response.text}"
            ) from exc

    # ------------------------------------------------------------------
    # Event translation
    # ------------------------------------------------------------------

    def _translate_event(self, raw: dict[str, Any]) -> VoxtraEvent | None:
        """Translate an ARI Stasis event to a VoxtraEvent.

        ARI event types:
        - StasisStart: New call entered Stasis app
        - StasisEnd: Call left Stasis app
        - ChannelDtmfReceived: DTMF digit pressed
        - ChannelHangupRequest: Hangup requested
        - ChannelDestroyed: Channel fully destroyed
        """
        event_type = raw.get("type", "")
        channel = raw.get("channel", {})
        channel_id = channel.get("id", "")

        # Generate a session ID from the channel ID
        session_id = channel_id

        if event_type == "StasisStart":
            caller_id = channel.get("caller", {}).get("number", "")
            callee_id = channel.get("dialplan", {}).get("exten", "")

            logger.info(
                "StasisStart: channel=%s caller=%s callee=%s",
                channel_id,
                caller_id,
                callee_id,
            )

            return CallStartedEvent(
                session_id=session_id,
                caller_id=caller_id,
                callee_id=callee_id,
                direction="inbound",
                data={"channel_id": channel_id, "raw": raw},
            )

        elif event_type == "StasisEnd":
            logger.info("StasisEnd: channel=%s", channel_id)
            return CallEndedEvent(
                session_id=session_id,
                reason="stasis_end",
                data={"channel_id": channel_id},
            )

        elif event_type == "ChannelDtmfReceived":
            digit = raw.get("digit", "")
            logger.debug("DTMF received: channel=%s digit=%s", channel_id, digit)
            return DTMFEvent(
                session_id=session_id,
                digit=digit,
                data={"channel_id": channel_id},
            )

        elif event_type in ("ChannelHangupRequest", "ChannelDestroyed"):
            cause_text = raw.get("cause_txt", "")
            logger.info(
                "%s: channel=%s cause=%s",
                event_type,
                channel_id,
                cause_text,
            )
            return CallEndedEvent(
                session_id=session_id,
                reason=cause_text or event_type,
                data={"channel_id": channel_id},
            )

        else:
            logger.debug("Unhandled ARI event type: %s", event_type)
            return None

    def _basic_auth_header(self) -> str:
        """Generate a Basic auth header value."""
        import base64

        credentials = f"{self.config.username}:{self.config.password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"
