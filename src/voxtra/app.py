"""VoxtraApp — the main entry point for a Voxtra application.

VoxtraApp is the central object developers use to build telephony AI
applications. It manages the ARI connection, listens for calls, and
dispatches them to user-defined handlers.

Design goals:
    1. Minimal boilerplate — 10 lines to a working call handler.
    2. Asterisk-native — built directly on ARI, not abstracted away.
    3. AudioSocket-first — clean TCP audio I/O, no RTP complexity.
    4. SaaS-ready — tenant isolation via ARI app namespacing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Callable, Coroutine
from typing import Any

from voxtra.ari.client import ARIClient
from voxtra.ari.events import ARIEvent
from voxtra.events import (
    CallEndedEvent,
    CallStartedEvent,
    DTMFEvent,
    EventType,
    VoxtraEvent,
)
from voxtra.session import CallSession
from voxtra.types import CallDirection

logger = logging.getLogger("voxtra")

# Type alias for the user's call handler
OnCallHandler = Callable[[CallSession], Coroutine[Any, Any, None]]


class VoxtraApp:
    """The main Voxtra application.

    Minimal usage — 10 lines to a working AI call handler::

        from voxtra import VoxtraApp

        app = VoxtraApp(
            ari_url="http://pbx.example.com:8088",
            ari_user="asterisk",
            ari_password="secret",
        )

        @app.on_call
        async def handle(call):
            await call.answer()
            await call.play_file("hello-world")
            await call.hangup()

        app.run()

    With routing::

        @app.on_call(extension="1000")
        async def support(call):
            await call.answer()
            await call.play_file("support-greeting")

        @app.on_call(extension="2000")
        async def sales(call):
            await call.answer()
            await call.play_file("sales-greeting")

    SaaS multi-tenant (ARI app namespacing)::

        app = VoxtraApp(
            ari_url="http://pbx:8088",
            ari_user="asterisk",
            ari_password="secret",
            app_name="tenant-acme",     # Isolates Stasis events
        )

    Originate outbound calls::

        call = await app.originate(
            endpoint="PJSIP/+265999123456@carrier",
            caller_id="+265888000001",
        )
    """

    def __init__(
        self,
        ari_url: str = "",
        ari_user: str = "",
        ari_password: str = "",
        *,
        app_name: str = "voxtra",
        reconnect_interval: float = 5.0,
        debug: bool = False,
    ) -> None:
        # ARI connection parameters (support env vars as fallback)
        self.ari_url = ari_url or os.environ.get("VOXTRA_ARI_URL", "http://localhost:8088")
        self.ari_user = ari_user or os.environ.get("VOXTRA_ARI_USER", "asterisk")
        self.ari_password = ari_password or os.environ.get("VOXTRA_ARI_PASSWORD", "")
        self.app_name = app_name
        self.debug = debug

        # ARI client (created on connect)
        self._ari: ARIClient | None = None
        self._reconnect_interval = reconnect_interval

        # Call handlers — keyed by extension pattern, None = default
        self._handlers: dict[str | None, OnCallHandler] = {}
        self._default_handler: OnCallHandler | None = None

        # Active sessions keyed by channel ID
        self._sessions: dict[str, CallSession] = {}

        # Lifecycle hooks
        self._on_startup: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self._on_shutdown: list[Callable[[], Coroutine[Any, Any, None]]] = []

        self._running = False

    # ------------------------------------------------------------------
    # Decorator API
    # ------------------------------------------------------------------

    def on_call(
        self,
        func: OnCallHandler | None = None,
        *,
        extension: str | None = None,
        number: str | None = None,
    ) -> Any:
        """Register a call handler.

        Can be used as a plain decorator or with arguments::

            # Default handler (all calls)
            @app.on_call
            async def handle(call): ...

            # Extension-specific
            @app.on_call(extension="1000")
            async def support(call): ...

            # Number-specific
            @app.on_call(number="+265999123456")
            async def specific_did(call): ...
        """
        def decorator(handler: OnCallHandler) -> OnCallHandler:
            if extension is not None:
                self._handlers[extension] = handler
            elif number is not None:
                self._handlers[f"num:{number}"] = handler
            else:
                self._default_handler = handler
            return handler

        # Support both @app.on_call and @app.on_call(extension="1000")
        if func is not None:
            return decorator(func)
        return decorator

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_startup(self, func: Callable[[], Coroutine[Any, Any, None]]) -> Callable:
        """Register an async function to run on application startup."""
        self._on_startup.append(func)
        return func

    def on_shutdown(self, func: Callable[[], Coroutine[Any, Any, None]]) -> Callable:
        """Register an async function to run on application shutdown."""
        self._on_shutdown.append(func)
        return func

    # ------------------------------------------------------------------
    # Outbound calling
    # ------------------------------------------------------------------

    async def originate(
        self,
        endpoint: str,
        *,
        caller_id: str = "",
        timeout: int = 30,
        variables: dict[str, str] | None = None,
    ) -> CallSession:
        """Originate an outbound call.

        Args:
            endpoint: SIP endpoint, e.g. "PJSIP/+265999123456@carrier".
            caller_id: Caller ID to present.
            timeout: Ring timeout in seconds.
            variables: Channel variables to set.

        Returns:
            A CallSession for the new outbound call.
        """
        if self._ari is None:
            raise RuntimeError("Not connected. Call start() or run() first.")

        channel = await self._ari.originate(
            endpoint,
            caller_id=caller_id,
            timeout=timeout,
            variables=variables,
        )

        session = CallSession(
            channel_id=channel.id,
            caller_id=caller_id,
            called_number=endpoint,
            direction=CallDirection.OUTBOUND,
            ari=self._ari,
            app_name=self.app_name,
        )
        self._sessions[session.id] = session

        logger.info(
            "Originated call to %s (channel=%s)",
            endpoint, channel.id,
        )

        return session

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> CallSession | None:
        """Retrieve an active session by ID."""
        return self._sessions.get(session_id)

    @property
    def active_sessions(self) -> dict[str, CallSession]:
        """Return all currently active call sessions."""
        return dict(self._sessions)

    # ------------------------------------------------------------------
    # ARI event handling
    # ------------------------------------------------------------------

    def _resolve_handler(self, called_number: str, caller_id: str) -> OnCallHandler | None:
        """Find the best handler for an incoming call."""
        # 1. Exact extension match
        if called_number in self._handlers:
            return self._handlers[called_number]

        # 2. Number match
        num_key = f"num:{caller_id}"
        if num_key in self._handlers:
            return self._handlers[num_key]

        # 3. Default handler
        return self._default_handler

    async def _handle_ari_event(self, event: ARIEvent) -> None:
        """Translate an ARI event and dispatch it."""
        if event.type == "StasisStart":
            await self._on_stasis_start(event)

        elif event.type == "StasisEnd":
            await self._on_stasis_end(event)

        elif event.type == "ChannelDtmfReceived":
            await self._on_dtmf(event)

        elif event.type in ("ChannelHangupRequest", "ChannelDestroyed"):
            await self._on_channel_hangup(event)

        else:
            logger.debug("Unhandled ARI event: %s", event.type)

    async def _on_stasis_start(self, event: ARIEvent) -> None:
        """Handle a new call entering the Stasis app."""
        if event.channel is None:
            return

        channel_id = event.channel.id
        caller_id = event.channel.caller_number
        called_number = event.channel.dialplan_exten

        # Skip if this is an external media channel we created
        if channel_id in self._sessions:
            return

        # Find handler
        handler = self._resolve_handler(called_number, caller_id)
        if handler is None:
            logger.warning(
                "No handler for call: caller=%s exten=%s — hanging up",
                caller_id, called_number,
            )
            if self._ari:
                await self._ari.hangup_channel(channel_id)
            return

        # Create session
        session = CallSession(
            channel_id=channel_id,
            caller_id=caller_id,
            called_number=called_number,
            direction=CallDirection.INBOUND,
            ari=self._ari,
            app_name=self.app_name,
        )
        self._sessions[session.id] = session

        logger.info(
            "New call: channel=%s caller=%s exten=%s",
            channel_id, caller_id, called_number,
        )

        # Run handler in a background task
        asyncio.create_task(self._run_handler(handler, session))

    async def _on_stasis_end(self, event: ARIEvent) -> None:
        """Handle a call leaving the Stasis app."""
        if event.channel is None:
            return

        channel_id = event.channel.id
        session = self._sessions.get(channel_id)
        if session:
            session.state = "completed"
            await session.push_event(VoxtraEvent(
                type=EventType.CALL_ENDED,
                session_id=channel_id,
                data={"reason": "stasis_end"},
            ))
            self._sessions.pop(channel_id, None)
            logger.info("Call ended: channel=%s", channel_id)

    async def _on_dtmf(self, event: ARIEvent) -> None:
        """Handle a DTMF digit received on a channel."""
        if event.channel is None:
            return

        channel_id = event.channel.id
        session = self._sessions.get(channel_id)
        if session:
            await session.push_event(VoxtraEvent(
                type=EventType.DTMF_RECEIVED,
                session_id=channel_id,
                data={"digit": event.digit},
            ))

    async def _on_channel_hangup(self, event: ARIEvent) -> None:
        """Handle a channel hangup/destroy."""
        if event.channel is None:
            return

        channel_id = event.channel.id
        session = self._sessions.get(channel_id)
        if session:
            session.state = "completed"
            await session.push_event(VoxtraEvent(
                type=EventType.CALL_ENDED,
                session_id=channel_id,
                data={"reason": event.cause_txt or event.type},
            ))
            await session._cleanup()
            self._sessions.pop(channel_id, None)
            logger.info("Channel hangup: channel=%s reason=%s", channel_id, event.cause_txt)

    async def _run_handler(self, handler: OnCallHandler, session: CallSession) -> None:
        """Execute a call handler with error handling."""
        try:
            await handler(session)
        except Exception:
            logger.exception("Error in call handler for session %s", session.id)
        finally:
            # Ensure cleanup even if handler didn't hang up
            if session.id in self._sessions:
                try:
                    await session.hangup()
                except Exception:
                    pass
                self._sessions.pop(session.id, None)

    # ------------------------------------------------------------------
    # Application lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Voxtra application (async version).

        Connects to ARI and begins listening for Stasis events.
        This method blocks until the application is stopped.
        """
        log_level = logging.DEBUG if self.debug else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        )

        logger.info(
            "Starting Voxtra app '%s' → %s",
            self.app_name, self.ari_url,
        )

        # Create and connect ARI client
        self._ari = ARIClient(
            base_url=self.ari_url,
            username=self.ari_user,
            password=self.ari_password,
            app_name=self.app_name,
            reconnect_interval=self._reconnect_interval,
        )
        await self._ari.connect()

        # Run startup hooks
        for hook in self._on_startup:
            await hook()

        self._running = True

        logger.info(
            "Voxtra app '%s' ready — listening for calls",
            self.app_name,
        )

        # Main event loop — listen for ARI events
        try:
            async for event in self._ari.events():
                if not self._running:
                    break
                try:
                    await self._handle_ari_event(event)
                except Exception:
                    logger.exception("Error handling ARI event: %s", event.type)
        except Exception:
            if self._running:
                logger.exception("ARI event stream error")

    async def stop(self) -> None:
        """Stop the Voxtra application gracefully."""
        logger.info("Stopping Voxtra app '%s'", self.app_name)
        self._running = False

        # Hang up all active calls
        for session in list(self._sessions.values()):
            try:
                await session.hangup()
            except Exception:
                logger.warning("Failed to hang up session %s", session.id)
        self._sessions.clear()

        # Close ARI connection
        if self._ari is not None:
            await self._ari.close()
            self._ari = None

        # Run shutdown hooks
        for hook in self._on_shutdown:
            try:
                await hook()
            except Exception:
                logger.exception("Error in shutdown hook")

        logger.info("Voxtra app '%s' stopped", self.app_name)

    def run(self) -> None:
        """Run the Voxtra application (blocking).

        Sets up signal handlers for graceful shutdown and runs
        the async event loop. Use this for standalone applications.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Graceful shutdown on SIGINT / SIGTERM
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(
                    sig, lambda: asyncio.ensure_future(self.stop())
                )
            except NotImplementedError:
                pass  # Windows

        try:
            loop.run_until_complete(self.start())
        except KeyboardInterrupt:
            loop.run_until_complete(self.stop())
        finally:
            loop.close()

    async def run_async(self) -> None:
        """Run the application within an existing async event loop.

        Use this when integrating Voxtra into a larger async application
        (e.g., a FastAPI server)::

            import asyncio
            from voxtra import VoxtraApp

            app = VoxtraApp(...)

            async def main():
                await app.run_async()

            asyncio.run(main())
        """
        await self.start()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def ari(self) -> ARIClient:
        """Access the underlying ARI client (for advanced use)."""
        if self._ari is None:
            raise RuntimeError("Not connected")
        return self._ari

    @property
    def is_running(self) -> bool:
        return self._running
