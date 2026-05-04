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
import warnings
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from voxtra.ai.llm.base import BaseAgent
from voxtra.ai.stt.base import BaseSTT
from voxtra.ai.tts.base import BaseTTS
from voxtra.ai.vad.base import BaseVAD
from voxtra.ari.client import ARIClient
from voxtra.ari.events import ARIEvent
from voxtra.config import AsteriskConfig, VoxtraConfig
from voxtra.core.pipeline import VoicePipeline
from voxtra.events import (
    EventType,
    VoxtraEvent,
)
from voxtra.exceptions import RouteNotFoundError
from voxtra.media.session_transport import CallSessionMediaTransport
from voxtra.recording.sinks import RecordingSink
from voxtra.registry import registry
from voxtra.router import Router
from voxtra.session import CallSession
from voxtra.telephony.asterisk import AsteriskAdapter
from voxtra.telephony.base import BaseTelephonyAdapter
from voxtra.types import CallDirection
from voxtra.webhooks import BackendWebhook

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

        @app.default()
        async def handle(call):
            await call.answer()
            await call.play_file("hello-world")
            await call.hangup()

        app.run()

    With routing::

        @app.route(extension="1000")
        async def support(call):
            await call.answer()
            await call.play_file("support-greeting")

        @app.route(extension="2000")
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
        router: Router | None = None,
        telephony: BaseTelephonyAdapter | None = None,
        stt: BaseSTT | None = None,
        llm: BaseAgent | None = None,
        tts: BaseTTS | None = None,
        vad: BaseVAD | None = None,
        webhook: BackendWebhook | None = None,
        recording_sink: RecordingSink | None = None,
    ) -> None:
        # ARI connection parameters (support env vars as fallback)
        self.ari_url = ari_url or os.environ.get("VOXTRA_ARI_URL", "http://localhost:8088")
        self.ari_user = ari_user or os.environ.get("VOXTRA_ARI_USER", "asterisk")
        self.ari_password = ari_password or os.environ.get("VOXTRA_ARI_PASSWORD", "")
        self.app_name = app_name
        self.debug = debug
        self._reconnect_interval = reconnect_interval

        # Telephony backend. If none provided, an AsteriskAdapter is built
        # lazily on start() from ari_url/ari_user/ari_password. This keeps
        # the legacy "VoxtraApp(ari_url=..., ari_user=..., ari_password=...)"
        # construction working unchanged.
        self._telephony: BaseTelephonyAdapter | None = telephony

        # Convenience handle to the underlying ARI client. Populated in start()
        # once the adapter is connected. Used by CallSession for ARI-specific
        # operations (bridges, externalMedia, etc.).
        self._ari: ARIClient | None = None

        # AI providers. When all three of stt/llm/tts are configured, a
        # VoicePipeline is auto-wired into every session via
        # _maybe_start_pipeline.
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._vad = vad

        # Routing — single source of truth for call dispatch
        self.router: Router = router or Router()

        # Optional backend webhook emitter. When set, every dispatched
        # VoxtraEvent is forwarded as a fire-and-forget HTTP POST. Failures
        # never propagate into the call pipeline.
        self._webhook: BackendWebhook | None = webhook

        # Optional default recording sink. Propagated onto every
        # CallSession; handlers can override per-call by passing
        # `sink=` to record_start.
        self._recording_sink: RecordingSink | None = recording_sink

        # Active sessions keyed by channel ID
        self._sessions: dict[str, CallSession] = {}

        # Lifecycle hooks
        self._on_startup: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self._on_shutdown: list[Callable[[], Coroutine[Any, Any, None]]] = []

        self._running = False

    @classmethod
    def with_asterisk(
        cls,
        *,
        ari_url: str,
        ari_user: str,
        ari_password: str,
        app_name: str = "voxtra",
        **kwargs: Any,
    ) -> VoxtraApp:
        """Build a VoxtraApp wired to an Asterisk telephony backend.

        Equivalent to ``VoxtraApp(telephony=AsteriskAdapter(...))`` but
        spells out the intent — the backend is Asterisk."""
        adapter = AsteriskAdapter(
            ari_url=ari_url,
            ari_user=ari_user,
            ari_password=ari_password,
            app_name=app_name,
        )
        return cls(telephony=adapter, app_name=app_name, **kwargs)

    @classmethod
    def from_config(cls, config: VoxtraConfig) -> VoxtraApp:
        """Build a VoxtraApp from a :class:`VoxtraConfig`.

        The telephony adapter is resolved from the registry by name
        (e.g. ``"asterisk"``) and instantiated from its provider-specific
        config block (``config.telephony.asterisk``).

        AI providers (STT/LLM/TTS/VAD) are not auto-instantiated here —
        construct them yourself and pass to :class:`VoxtraApp` directly,
        or build them post-construction. This avoids forcing every
        provider package to be importable just to load a config.

        If ``config.backend.webhook.url`` is set, a :class:`BackendWebhook`
        is constructed automatically.
        """
        adapter = cls._build_adapter_from_config(config)
        webhook: BackendWebhook | None = None
        webhook_cfg = (
            config.backend.webhook if config.backend is not None else None
        )
        if webhook_cfg is not None and webhook_cfg.url:
            webhook = BackendWebhook(webhook_cfg)
        return cls(
            telephony=adapter,
            app_name=config.app_name,
            debug=config.server.debug,
            webhook=webhook,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> VoxtraApp:
        """Load a YAML config and build a VoxtraApp from it.

        Equivalent to ``VoxtraApp.from_config(VoxtraConfig.from_yaml(path))``.
        """
        return cls.from_config(VoxtraConfig.from_yaml(path))

    @staticmethod
    def _build_adapter_from_config(config: VoxtraConfig) -> BaseTelephonyAdapter:
        """Resolve and instantiate the telephony adapter from config."""
        provider = config.telephony.provider
        adapter_cls = registry.resolve_telephony(provider)

        # Asterisk is special-cased because it carries a typed config
        # block. Other adapters can either (a) provide their own
        # ``from_config`` classmethod or (b) accept an instantiated
        # provider and skip this path.
        if provider == "asterisk":
            asterisk_cfg = config.telephony.asterisk or AsteriskConfig(
                app_name=config.app_name
            )
            return adapter_cls.from_config(asterisk_cfg)

        # Generic path — caller's adapter must accept zero args or have
        # its own from_config(VoxtraConfig). For the unblocking case we
        # just try the no-arg constructor.
        if hasattr(adapter_cls, "from_config"):
            return adapter_cls.from_config(config)
        return adapter_cls()

    @property
    def telephony(self) -> BaseTelephonyAdapter:
        """The configured telephony adapter.

        Built lazily from ARI kwargs on first access if none was passed
        to the constructor. Most code should use this instead of poking
        at :attr:`_ari` directly.
        """
        if self._telephony is None:
            self._telephony = AsteriskAdapter(
                ari_url=self.ari_url,
                ari_user=self.ari_user,
                ari_password=self.ari_password,
                app_name=self.app_name,
                reconnect_interval=self._reconnect_interval,
            )
        return self._telephony

    # ------------------------------------------------------------------
    # Decorator API
    # ------------------------------------------------------------------

    def route(
        self,
        *,
        extension: str | None = None,
        number: str | None = None,
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[OnCallHandler], OnCallHandler]:
        """Register a call handler for an extension or number.

        Usage::

            @app.route(extension="1000")
            async def support(call): ...

            @app.route(number="+265888111111", metadata={"vip": True})
            async def vip(call): ...
        """
        return self.router.route(
            extension=extension,
            number=number,
            name=name,
            metadata=metadata,
        )

    def default(self) -> Callable[[OnCallHandler], OnCallHandler]:
        """Register the fallback handler used when no route matches.

        Usage::

            @app.default()
            async def fallback(call): ...
        """
        return self.router.default()

    # Compatibility alias — both names exist in examples and downstream code.
    default_route = default

    def on_call(
        self,
        func: OnCallHandler | None = None,
        *,
        extension: str | None = None,
        number: str | None = None,
    ) -> Any:
        """Deprecated alias for :meth:`route` / :meth:`default`.

        Prefer ``@app.route(extension="1000")`` and ``@app.default()``.
        """
        warnings.warn(
            "VoxtraApp.on_call is deprecated; use @app.route(extension=...) "
            "or @app.default() instead",
            DeprecationWarning,
            stacklevel=2,
        )

        def register(handler: OnCallHandler) -> OnCallHandler:
            if extension is not None or number is not None:
                self.router.route(extension=extension, number=number)(handler)
            else:
                self.router.default()(handler)
            return handler

        # Support both @app.on_call and @app.on_call(extension="1000")
        if func is not None:
            return register(func)
        return register

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
        session._default_recording_sink = self._recording_sink
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

    def _emit_webhook(self, event: VoxtraEvent) -> None:
        """Fire-and-forget webhook delivery.

        Schedules the POST as a background task so the call pipeline
        never blocks on the receiver. Errors are swallowed inside the
        emitter and logged at WARNING.
        """
        if self._webhook is None:
            return
        asyncio.create_task(self._webhook.emit(event))

    def _maybe_start_pipeline(self, session: CallSession) -> None:
        """Auto-wire :class:`VoicePipeline` to a session if STT/LLM/TTS configured.

        No-op when any of stt/llm/tts is missing — sessions without the
        full AI stack are still valid (e.g. plain IVR menus).

        The pipeline's events are routed back into the session's event
        queue so :meth:`CallSession.listen` can wait on USER_TRANSCRIPT.
        """
        if self._stt is None or self._llm is None or self._tts is None:
            return

        transport = CallSessionMediaTransport(session)
        pipeline = VoicePipeline(
            media=transport,
            stt=self._stt,
            llm=self._llm,
            tts=self._tts,
            vad=self._vad,
            event_callback=session.push_event,
        )
        session._pipeline = pipeline
        session._pipeline_task = asyncio.create_task(
            pipeline.run(session_id=session.id)
        )

    async def _resolve_handler(
        self, called_number: str, caller_id: str
    ) -> tuple[OnCallHandler | None, dict[str, Any]]:
        """Find the best handler and any associated metadata for an incoming call.

        Returns a ``(handler, metadata)`` tuple. ``handler`` is None when
        nothing matches (and no default is registered). ``metadata`` is the
        matched static route's metadata, or an empty dict for default /
        dispatch-rule matches.
        """
        # Find any matching static route's metadata (for merging into the session).
        # Dispatch rules and the default handler don't carry route metadata.
        metadata: dict[str, Any] = {}
        for route in self.router.routes:
            if route.matches(extension=called_number, number=caller_id):
                metadata = dict(route.metadata)
                break

        try:
            handler = await self.router.resolve(
                extension=called_number, number=caller_id
            )
        except RouteNotFoundError:
            return None, {}
        return handler, metadata

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

    async def _handle_voxtra_event(self, event: VoxtraEvent) -> None:
        """Dispatch a backend-agnostic VoxtraEvent.

        Used when the telephony adapter is not Asterisk (the Asterisk
        path consumes ARIEvents directly so ARI-specific session work
        keeps working). Non-Asterisk backends create CallSessions
        without an ARIClient — only adapter-level methods are usable.
        """
        self._emit_webhook(event)

        if event.type == EventType.CALL_STARTED:
            session_id = event.session_id
            if session_id in self._sessions:
                return

            caller_id = getattr(event, "caller_id", "")
            callee_id = getattr(event, "callee_id", "")
            direction_raw = getattr(event, "direction", "inbound")
            direction = (
                CallDirection.OUTBOUND
                if direction_raw == "outbound"
                else CallDirection.INBOUND
            )

            handler, route_metadata = await self._resolve_handler(callee_id, caller_id)
            if handler is None:
                logger.warning(
                    "No handler for call: caller=%s callee=%s — dropping",
                    caller_id, callee_id,
                )
                return

            session = CallSession(
                channel_id=session_id,
                caller_id=caller_id,
                called_number=callee_id,
                direction=direction,
                ari=self._ari,
                app_name=self.app_name,
            )
            if route_metadata:
                session.metadata.update(route_metadata)
            session._default_recording_sink = self._recording_sink
            self._sessions[session.id] = session
            self._maybe_start_pipeline(session)
            asyncio.create_task(self._run_handler(handler, session))

        elif event.type == EventType.CALL_ENDED:
            session = self._sessions.pop(event.session_id, None)
            if session is not None:
                await session.push_event(event)

        elif event.type == EventType.DTMF_RECEIVED:
            session = self._sessions.get(event.session_id)
            if session is not None:
                await session.push_event(event)

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
        handler, route_metadata = await self._resolve_handler(called_number, caller_id)
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
        if route_metadata:
            session.metadata.update(route_metadata)
        session._default_recording_sink = self._recording_sink
        self._sessions[session.id] = session

        # Auto-wire AI pipeline if configured (no-op otherwise).
        self._maybe_start_pipeline(session)

        logger.info(
            "New call: channel=%s caller=%s exten=%s",
            channel_id, caller_id, called_number,
        )

        self._emit_webhook(VoxtraEvent(
            type=EventType.CALL_STARTED,
            session_id=channel_id,
            data={
                "caller_id": caller_id,
                "called_number": called_number,
                "direction": "inbound",
            },
        ))

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
            ended = VoxtraEvent(
                type=EventType.CALL_ENDED,
                session_id=channel_id,
                data={"reason": "stasis_end"},
            )
            await session.push_event(ended)
            self._emit_webhook(ended)
            self._sessions.pop(channel_id, None)
            logger.info("Call ended: channel=%s", channel_id)

    async def _on_dtmf(self, event: ARIEvent) -> None:
        """Handle a DTMF digit received on a channel."""
        if event.channel is None:
            return

        channel_id = event.channel.id
        session = self._sessions.get(channel_id)
        if session:
            dtmf = VoxtraEvent(
                type=EventType.DTMF_RECEIVED,
                session_id=channel_id,
                data={"digit": event.digit},
            )
            await session.push_event(dtmf)
            self._emit_webhook(dtmf)

    async def _on_channel_hangup(self, event: ARIEvent) -> None:
        """Handle a channel hangup/destroy."""
        if event.channel is None:
            return

        channel_id = event.channel.id
        session = self._sessions.get(channel_id)
        if session:
            session.state = "completed"
            ended = VoxtraEvent(
                type=EventType.CALL_ENDED,
                session_id=channel_id,
                data={"reason": event.cause_txt or event.type},
            )
            await session.push_event(ended)
            self._emit_webhook(ended)
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

        Connects to the telephony backend and begins dispatching events.
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

        # Connect via the telephony adapter (lazily-built AsteriskAdapter
        # by default). For Asterisk, expose the underlying ARIClient for
        # CallSession's ARI-specific operations.
        adapter = self.telephony
        await adapter.connect()
        if isinstance(adapter, AsteriskAdapter):
            self._ari = adapter.client

        # Run startup hooks
        for hook in self._on_startup:
            await hook()

        self._running = True

        logger.info(
            "Voxtra app '%s' ready — listening for calls",
            self.app_name,
        )

        # Main event loop — drive the adapter's ARI event stream through
        # the existing ARI-event dispatch path. This keeps CallSession's
        # ARI-specific behaviour intact while making the adapter the
        # source of truth for backend selection.
        if isinstance(adapter, AsteriskAdapter):
            try:
                async for event in adapter.client.events():
                    if not self._running:
                        break
                    try:
                        await self._handle_ari_event(event)
                    except Exception:
                        logger.exception("Error handling ARI event: %s", event.type)
            except Exception:
                if self._running:
                    logger.exception("ARI event stream error")
        else:
            # Non-Asterisk backends: dispatch translated VoxtraEvents.
            await adapter.listen(self._handle_voxtra_event)

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

        # Disconnect via the adapter so non-Asterisk backends shut down
        # cleanly too.
        if self._telephony is not None:
            try:
                await self._telephony.disconnect()
            except Exception:
                logger.exception("Error disconnecting telephony adapter")
        self._ari = None

        # Release the webhook HTTP client (only owned ones — passing your
        # own httpx.AsyncClient keeps it alive).
        if self._webhook is not None:
            try:
                await self._webhook.aclose()
            except Exception:
                logger.exception("Error closing webhook emitter")

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
