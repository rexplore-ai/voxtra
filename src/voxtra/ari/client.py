"""ARIClient — async HTTP + WebSocket client for Asterisk REST Interface.

Handles:
- HTTP REST calls for channel/bridge/playback control
- WebSocket event streaming with automatic reconnection
- Basic auth for both HTTP and WS connections
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx

from voxtra.ari.events import ARIEvent, parse_ari_event
from voxtra.ari.models import Bridge, Channel, Playback
from voxtra.exceptions import TelephonyConnectionError, TelephonyError

logger = logging.getLogger("voxtra.ari.client")


class ARIClient:
    """Async client for the Asterisk REST Interface.

    Provides both HTTP REST methods and a WebSocket event stream
    with automatic reconnection.

    Usage::

        client = ARIClient(
            base_url="http://pbx.example.com:8088",
            username="asterisk",
            password="secret",
            app_name="voxtra",
        )
        await client.connect()

        # REST operations
        await client.answer_channel("channel-id")
        await client.hangup_channel("channel-id")

        # Event stream
        async for event in client.events():
            print(event.type, event.channel)

        await client.close()
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        app_name: str = "voxtra",
        reconnect_interval: float = 5.0,
        max_reconnect_attempts: int = 0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.app_name = app_name
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts

        self._http: httpx.AsyncClient | None = None
        self._ws: Any = None
        self._connected = False
        self._closing = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> dict[str, Any]:
        """Connect to ARI HTTP and verify connectivity.

        Returns:
            Asterisk system info dict from GET /ari/asterisk/info.

        Raises:
            TelephonyConnectionError: If connection fails.
        """
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            auth=(self.username, self.password),
            timeout=30.0,
        )

        try:
            resp = await self._http.get("/ari/asterisk/info")
            resp.raise_for_status()
            info = resp.json()
            self._connected = True
            logger.info(
                "Connected to Asterisk ARI at %s (version=%s)",
                self.base_url,
                info.get("build", {}).get("version", "unknown"),
            )
            return info
        except httpx.HTTPError as exc:
            await self._cleanup_http()
            raise TelephonyConnectionError(
                f"Failed to connect to ARI at {self.base_url}: {exc}"
            ) from exc

    async def close(self) -> None:
        """Close all connections gracefully."""
        self._closing = True
        self._connected = False

        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        await self._cleanup_http()
        logger.info("ARI client closed")

    async def _cleanup_http(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # WebSocket event stream with reconnection
    # ------------------------------------------------------------------

    async def events(self) -> AsyncIterator[ARIEvent]:
        """Stream ARI Stasis events via WebSocket.

        Automatically reconnects on disconnect (up to max_reconnect_attempts,
        0 = infinite retries).

        Yields:
            Parsed ARIEvent objects for each Stasis event.
        """
        attempts = 0

        while not self._closing:
            try:
                async for event in self._ws_stream():
                    yield event
                    attempts = 0  # reset on successful message

                # Clean exit (server closed gracefully)
                if self._closing:
                    break

            except Exception as exc:
                if self._closing:
                    break

                attempts += 1
                if self.max_reconnect_attempts > 0 and attempts > self.max_reconnect_attempts:
                    logger.error(
                        "ARI WebSocket: max reconnect attempts (%d) exceeded",
                        self.max_reconnect_attempts,
                    )
                    raise TelephonyConnectionError(
                        f"ARI WebSocket reconnection failed after {attempts} attempts: {exc}"
                    ) from exc

                logger.warning(
                    "ARI WebSocket disconnected (%s). Reconnecting in %.1fs (attempt %d)...",
                    exc,
                    self.reconnect_interval,
                    attempts,
                )
                await asyncio.sleep(self.reconnect_interval)

    async def _ws_stream(self) -> AsyncIterator[ARIEvent]:
        """Open a single WebSocket connection and yield events until disconnect."""
        try:
            import websockets
        except ImportError:
            raise TelephonyError(
                "websockets package is required. Install with: pip install websockets"
            )

        ws_base = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/ari/events?app={self.app_name}"

        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()

        logger.info("Connecting to ARI WebSocket: %s", ws_url)

        self._ws = await websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Basic {credentials}"},
        )

        logger.info("ARI WebSocket connected")

        try:
            async for message in self._ws:
                try:
                    raw = json.loads(message)
                    yield parse_ari_event(raw)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON ARI message: %s", str(message)[:200])
        finally:
            if self._ws is not None:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None

    # ------------------------------------------------------------------
    # Channel operations
    # ------------------------------------------------------------------

    async def answer_channel(self, channel_id: str) -> None:
        """Answer a ringing channel."""
        await self._post(f"/ari/channels/{channel_id}/answer")

    async def hangup_channel(self, channel_id: str, reason: str = "normal") -> None:
        """Hang up a channel."""
        await self._delete(f"/ari/channels/{channel_id}", params={"reason": reason})

    async def get_channel(self, channel_id: str) -> Channel:
        """Get channel details."""
        data = await self._get(f"/ari/channels/{channel_id}")
        return Channel.from_ari(data)

    async def list_channels(self) -> list[Channel]:
        """List all active channels."""
        data = await self._get("/ari/channels")
        return [Channel.from_ari(ch) for ch in data]

    async def originate(
        self,
        endpoint: str,
        *,
        app: str | None = None,
        caller_id: str = "",
        timeout: int = 30,
        variables: dict[str, str] | None = None,
    ) -> Channel:
        """Originate (create) an outbound call.

        Args:
            endpoint: SIP endpoint (e.g. "PJSIP/+265123456789@trunk-endpoint").
            app: Stasis app name (defaults to self.app_name).
            caller_id: Caller ID string.
            timeout: Ring timeout in seconds.
            variables: Channel variables to set.

        Returns:
            The newly created Channel.
        """
        params: dict[str, Any] = {
            "endpoint": endpoint,
            "app": app or self.app_name,
            "timeout": timeout,
        }
        if caller_id:
            params["callerId"] = caller_id
        if variables:
            params["variables"] = json.dumps({"variables": variables})

        data = await self._post("/ari/channels", params=params)
        return Channel.from_ari(data)

    async def redirect_channel(self, channel_id: str, endpoint: str) -> None:
        """Redirect a channel to a new endpoint (blind transfer)."""
        await self._post(
            f"/ari/channels/{channel_id}/redirect",
            params={"endpoint": endpoint},
        )

    async def moh_start(self, channel_id: str, moh_class: str = "default") -> None:
        """Start music on hold on a channel."""
        await self._post(
            f"/ari/channels/{channel_id}/moh",
            params={"mohClass": moh_class},
        )

    async def moh_stop(self, channel_id: str) -> None:
        """Stop music on hold."""
        await self._delete(f"/ari/channels/{channel_id}/moh")

    async def send_dtmf(self, channel_id: str, dtmf: str) -> None:
        """Send DTMF digits on a channel."""
        await self._post(
            f"/ari/channels/{channel_id}/dtmf",
            params={"dtmf": dtmf},
        )

    async def set_channel_var(self, channel_id: str, variable: str, value: str) -> None:
        """Set a channel variable."""
        await self._post(
            f"/ari/channels/{channel_id}/variable",
            params={"variable": variable, "value": value},
        )

    async def snoop_channel(
        self,
        channel_id: str,
        *,
        app: str | None = None,
        spy: str = "both",
        whisper: str = "none",
    ) -> Channel:
        """Create a snoop channel for audio monitoring/injection.

        Args:
            channel_id: Channel to snoop on.
            spy: "none", "both", "out", "in" — which direction to spy.
            whisper: "none", "both", "out", "in" — which direction to whisper into.

        Returns:
            The snoop Channel.
        """
        params: dict[str, str] = {
            "app": app or self.app_name,
            "spy": spy,
            "whisper": whisper,
        }
        data = await self._post(f"/ari/channels/{channel_id}/snoop", params=params)
        return Channel.from_ari(data)

    async def create_external_media(
        self,
        external_host: str,
        *,
        app: str | None = None,
        fmt: str = "ulaw",
        encapsulation: str = "rtp",
        transport: str = "udp",
    ) -> Channel:
        """Create an external media channel (for RTP audio I/O)."""
        params = {
            "app": app or self.app_name,
            "external_host": external_host,
            "format": fmt,
            "encapsulation": encapsulation,
            "transport": transport,
        }
        data = await self._post("/ari/channels/externalMedia", params=params)
        return Channel.from_ari(data)

    # ------------------------------------------------------------------
    # Bridge operations
    # ------------------------------------------------------------------

    async def create_bridge(
        self,
        bridge_type: str = "mixing",
        name: str = "",
    ) -> Bridge:
        """Create a new bridge."""
        bridge_id = uuid4().hex[:12]
        params: dict[str, str] = {
            "type": bridge_type,
            "bridgeId": bridge_id,
        }
        if name:
            params["name"] = name
        data = await self._post("/ari/bridges", params=params)
        return Bridge.from_ari(data)

    async def add_to_bridge(self, bridge_id: str, channel_ids: list[str]) -> None:
        """Add channels to a bridge."""
        await self._post(
            f"/ari/bridges/{bridge_id}/addChannel",
            params={"channel": ",".join(channel_ids)},
        )

    async def remove_from_bridge(self, bridge_id: str, channel_ids: list[str]) -> None:
        """Remove channels from a bridge."""
        await self._post(
            f"/ari/bridges/{bridge_id}/removeChannel",
            params={"channel": ",".join(channel_ids)},
        )

    async def destroy_bridge(self, bridge_id: str) -> None:
        """Destroy a bridge."""
        await self._delete(f"/ari/bridges/{bridge_id}")

    # ------------------------------------------------------------------
    # Playback operations
    # ------------------------------------------------------------------

    async def play_on_channel(
        self,
        channel_id: str,
        media: str,
        *,
        lang: str = "",
    ) -> Playback:
        """Play audio on a channel.

        Args:
            channel_id: Target channel.
            media: Media URI — "sound:hello-world", "recording:abc",
                   "tone:ring", or "number:42".
            lang: Language for sound files.
        """
        params: dict[str, str] = {"media": media}
        if lang:
            params["lang"] = lang
        data = await self._post(f"/ari/channels/{channel_id}/play", params=params)
        return Playback.from_ari(data)

    async def stop_playback(self, playback_id: str) -> None:
        """Stop an active playback."""
        await self._delete(f"/ari/playbacks/{playback_id}")

    # ------------------------------------------------------------------
    # Recording operations
    # ------------------------------------------------------------------

    async def record_channel(
        self,
        channel_id: str,
        name: str,
        *,
        fmt: str = "wav",
        max_duration: int = 0,
        max_silence: int = 0,
        beep: bool = False,
        terminate_on: str = "none",
    ) -> dict[str, Any]:
        """Start recording a channel.

        Args:
            channel_id: Channel to record.
            name: Recording name (used for retrieval).
            fmt: Audio format (wav, gsm, etc.).
            max_duration: Max recording length in seconds (0 = unlimited).
            max_silence: Stop after this many seconds of silence.
            beep: Play a beep before recording.
            terminate_on: DTMF key to stop recording ("none", "#", "*", "any").
        """
        params: dict[str, Any] = {
            "name": name,
            "format": fmt,
            "maxDurationSeconds": max_duration,
            "maxSilenceSeconds": max_silence,
            "beep": beep,
            "terminateOn": terminate_on,
        }
        return await self._post(f"/ari/channels/{channel_id}/record", params=params)

    async def stop_recording(self, recording_name: str) -> None:
        """Stop a live recording."""
        await self._post(f"/ari/recordings/live/{recording_name}/stop")

    # ------------------------------------------------------------------
    # Module / config management
    # ------------------------------------------------------------------

    async def reload_module(self, module_name: str) -> None:
        """Reload an Asterisk module via ARI.

        Uses ``PUT /ari/asterisk/modules/{module}`` which performs an
        in-place reload — equivalent to ``module reload <name>`` on the
        Asterisk CLI but without shelling out.

        Common modules to reload after provisioning a tenant:

        * ``res_pjsip.so`` — picks up new endpoint/auth/aor/identify
          fragments included from ``pjsip.conf``.
        * ``pbx_config.so`` — picks up new dialplan contexts from
          ``extensions.conf`` includes.
        """
        await self._put(f"/ari/asterisk/modules/{module_name}")

    async def list_modules(self) -> list[dict[str, Any]]:
        """List all loaded Asterisk modules."""
        return await self._get("/ari/asterisk/modules")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._http is None:
            raise TelephonyError("ARI client not connected")
        try:
            resp = await self._http.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise TelephonyError(
                f"ARI GET {path} failed: {exc.response.status_code} {exc.response.text}"
            ) from exc

    async def _post(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._http is None:
            raise TelephonyError("ARI client not connected")
        try:
            resp = await self._http.post(path, params=params)
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}
        except httpx.HTTPStatusError as exc:
            raise TelephonyError(
                f"ARI POST {path} failed: {exc.response.status_code} {exc.response.text}"
            ) from exc

    async def _put(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._http is None:
            raise TelephonyError("ARI client not connected")
        try:
            resp = await self._http.put(path, params=params)
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {}
        except httpx.HTTPStatusError as exc:
            raise TelephonyError(
                f"ARI PUT {path} failed: {exc.response.status_code} {exc.response.text}"
            ) from exc

    async def _delete(self, path: str, params: dict[str, Any] | None = None) -> None:
        if self._http is None:
            raise TelephonyError("ARI client not connected")
        try:
            resp = await self._http.delete(path, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TelephonyError(
                f"ARI DELETE {path} failed: {exc.response.status_code} {exc.response.text}"
            ) from exc

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> ARIClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
