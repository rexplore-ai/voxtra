"""VoxtraApp — the main entry point for a Voxtra application.

VoxtraApp wires together telephony, media, AI providers, and routing
into a single cohesive application that developers interact with.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any, Callable, Coroutine

from voxtra.config import VoxtraConfig
from voxtra.events import CallStartedEvent, EventType, VoxtraEvent
from voxtra.exceptions import ConfigurationError
from voxtra.middleware import BaseMiddleware
from voxtra.router import CallHandler, Router
from voxtra.session import CallSession
from voxtra.types import CallDirection

logger = logging.getLogger("voxtra")


class VoxtraApp:
    """The main Voxtra application.

    Typical usage::

        from voxtra import VoxtraApp

        app = VoxtraApp.from_yaml("voxtra.yaml")

        @app.route(extension="1000")
        async def support(session):
            await session.say("Hello!")

        app.run()

    Or programmatically::

        from voxtra import VoxtraApp
        from voxtra.config import VoxtraConfig, AsteriskConfig, TelephonyConfig

        config = VoxtraConfig(
            telephony=TelephonyConfig(
                provider="asterisk",
                asterisk=AsteriskConfig(base_url="http://localhost:8088"),
            ),
        )
        app = VoxtraApp(config=config)
    """

    def __init__(
        self,
        config: VoxtraConfig | None = None,
        *,
        telephony: Any | None = None,
        media: Any | None = None,
        stt: Any | None = None,
        tts: Any | None = None,
        llm: Any | None = None,
    ) -> None:
        self.config = config or VoxtraConfig()
        self.router = Router()
        self._middlewares: list[BaseMiddleware] = []

        # Components can be injected directly or resolved from config later
        self._telephony = telephony
        self._media = media
        self._stt = stt
        self._tts = tts
        self._llm = llm

        # Active sessions keyed by session ID
        self._sessions: dict[str, CallSession] = {}

        # Lifecycle hooks
        self._on_startup: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self._on_shutdown: list[Callable[[], Coroutine[Any, Any, None]]] = []

        self._running = False

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> VoxtraApp:
        """Create a VoxtraApp from a YAML configuration file."""
        config = VoxtraConfig.from_yaml(path)
        return cls(config=config)

    # ------------------------------------------------------------------
    # Decorator API (delegates to internal Router)
    # ------------------------------------------------------------------

    def route(
        self,
        *,
        extension: str | None = None,
        number: str | None = None,
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[CallHandler], CallHandler]:
        """Decorator to register a call handler.

        Args:
            extension: Asterisk extension to match.
            number: Phone number to match.
            name: Human-readable name for the route.
            metadata: Arbitrary metadata for the route.

        Example::

            @app.route(extension="1000")
            async def handle_support(session: CallSession):
                await session.say("Hello!")
        """
        return self.router.route(
            extension=extension,
            number=number,
            name=name,
            metadata=metadata,
        )

    def default_route(self) -> Callable[[CallHandler], CallHandler]:
        """Decorator to register a default fallback handler."""
        return self.router.default()

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    def add_middleware(self, middleware: BaseMiddleware) -> None:
        """Add a middleware to the event processing pipeline."""
        self._middlewares.append(middleware)

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_startup(self, func: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Register an async function to run on application startup."""
        self._on_startup.append(func)

    def on_shutdown(self, func: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Register an async function to run on application shutdown."""
        self._on_shutdown.append(func)

    # ------------------------------------------------------------------
    # Component resolution
    # ------------------------------------------------------------------

    async def _resolve_components(self) -> None:
        """Resolve telephony, media, and AI components from config.

        If components were injected directly, they take precedence.
        Otherwise, we instantiate them based on the configuration.
        """
        # Telephony adapter
        if self._telephony is None:
            self._telephony = await self._create_telephony_adapter()

        # Media transport
        if self._media is None:
            self._media = await self._create_media_transport()

        # AI providers
        if self._stt is None:
            self._stt = self._create_stt_provider()
        if self._tts is None:
            self._tts = self._create_tts_provider()
        if self._llm is None:
            self._llm = self._create_llm_provider()

    async def _create_telephony_adapter(self) -> Any:
        """Create a telephony adapter based on config."""
        provider = self.config.telephony.provider

        if provider == "asterisk":
            from voxtra.telephony.asterisk.adapter import AsteriskARIAdapter

            if self.config.telephony.asterisk is None:
                raise ConfigurationError("Asterisk config required when provider='asterisk'")
            adapter = AsteriskARIAdapter(config=self.config.telephony.asterisk)
            return adapter

        elif provider == "livekit":
            from voxtra.telephony.livekit.adapter import LiveKitAdapter

            if self.config.telephony.livekit is None:
                raise ConfigurationError("LiveKit config required when provider='livekit'")
            adapter = LiveKitAdapter(config=self.config.telephony.livekit)
            return adapter

        raise ConfigurationError(f"Unknown telephony provider: {provider}")

    async def _create_media_transport(self) -> Any:
        """Create a media transport based on config."""
        from voxtra.media.websocket import WebSocketMediaTransport

        transport = WebSocketMediaTransport(config=self.config.media)
        return transport

    def _create_stt_provider(self) -> Any:
        """Create an STT provider based on config."""
        provider = self.config.ai.stt.provider

        if provider == "deepgram":
            from voxtra.ai.stt.deepgram import DeepgramSTT

            return DeepgramSTT(config=self.config.ai.stt)

        raise ConfigurationError(f"Unknown STT provider: {provider}")

    def _create_tts_provider(self) -> Any:
        """Create a TTS provider based on config."""
        provider = self.config.ai.tts.provider

        if provider == "elevenlabs":
            from voxtra.ai.tts.elevenlabs import ElevenLabsTTS

            return ElevenLabsTTS(config=self.config.ai.tts)

        raise ConfigurationError(f"Unknown TTS provider: {provider}")

    def _create_llm_provider(self) -> Any:
        """Create an LLM agent based on config."""
        provider = self.config.ai.llm.provider

        if provider == "openai":
            from voxtra.ai.llm.openai import OpenAIAgent

            return OpenAIAgent(config=self.config.ai.llm)

        raise ConfigurationError(f"Unknown LLM provider: {provider}")

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _create_session(self, event: CallStartedEvent) -> CallSession:
        """Create a new CallSession for an incoming call."""
        session = CallSession(
            session_id=event.session_id,
            caller_id=event.caller_id,
            callee_id=event.callee_id,
            direction=CallDirection(event.direction),
            telephony=self._telephony,
            media=self._media,
            stt=self._stt,
            tts=self._tts,
            agent=self._llm,
            channel_id=event.data.get("channel_id", ""),
        )
        self._sessions[session.id] = session
        logger.info(
            "Created session %s (caller=%s, callee=%s)",
            session.id,
            session.caller_id,
            session.callee_id,
        )
        return session

    def get_session(self, session_id: str) -> CallSession | None:
        """Retrieve an active session by ID."""
        return self._sessions.get(session_id)

    async def _destroy_session(self, session_id: str) -> None:
        """Clean up a completed session."""
        session = self._sessions.pop(session_id, None)
        if session:
            logger.info("Destroyed session %s", session_id)

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    async def _dispatch_event(self, event: VoxtraEvent) -> None:
        """Dispatch an event through middleware, then to the appropriate handler."""

        async def final_handler(evt: VoxtraEvent) -> VoxtraEvent | None:
            await self._handle_event(evt)
            return evt

        # Build middleware chain (outermost first)
        handler = final_handler
        for mw in reversed(self._middlewares):

            async def make_next(
                m: BaseMiddleware, nxt: Any
            ) -> Callable[..., Coroutine[Any, Any, VoxtraEvent | None]]:
                async def wrapped(e: VoxtraEvent) -> VoxtraEvent | None:
                    return await m.process(e, nxt)

                return wrapped

            handler = await make_next(mw, handler)

        await handler(event)

    async def _handle_event(self, event: VoxtraEvent) -> None:
        """Core event handler — routes calls and pushes events to sessions."""
        if event.type == EventType.CALL_STARTED:
            assert isinstance(event, CallStartedEvent)
            session = await self._create_session(event)

            # Resolve the handler for this call
            handler = await self.router.resolve(
                extension=event.callee_id,
                number=event.caller_id,
                call_info={
                    "caller_id": event.caller_id,
                    "callee_id": event.callee_id,
                    "direction": event.direction,
                },
            )

            # Run the handler in a background task
            asyncio.create_task(self._run_handler(handler, session))

        elif event.type == EventType.CALL_ENDED:
            await self._destroy_session(event.session_id)

        else:
            # Push event to the relevant session
            session = self._sessions.get(event.session_id)
            if session:
                await session.push_event(event)

    async def _run_handler(self, handler: CallHandler, session: CallSession) -> None:
        """Execute a call handler with error handling."""
        try:
            await handler(session)
        except Exception:
            logger.exception("Error in call handler for session %s", session.id)
        finally:
            if session.id in self._sessions:
                await self._destroy_session(session.id)

    # ------------------------------------------------------------------
    # Application lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Voxtra application (async version)."""
        logger.info("Starting Voxtra application '%s'", self.config.app_name)

        # Resolve components
        await self._resolve_components()

        # Run startup hooks
        for hook in self._on_startup:
            await hook()

        self._running = True

        # Connect telephony adapter and start listening
        if self._telephony is not None:
            await self._telephony.connect()
            await self._telephony.listen(callback=self._dispatch_event)

    async def stop(self) -> None:
        """Stop the Voxtra application gracefully."""
        logger.info("Stopping Voxtra application '%s'", self.config.app_name)
        self._running = False

        # Hang up all active calls
        for session in list(self._sessions.values()):
            try:
                await session.hangup()
            except Exception:
                logger.warning("Failed to hang up session %s", session.id)

        # Disconnect telephony
        if self._telephony is not None:
            await self._telephony.disconnect()

        # Run shutdown hooks
        for hook in self._on_shutdown:
            await hook()

        logger.info("Voxtra application stopped")

    def run(self) -> None:
        """Run the Voxtra application (blocking).

        Sets up signal handlers for graceful shutdown and runs
        the async event loop.
        """
        logging.basicConfig(
            level=logging.DEBUG if self.config.server.debug else logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Graceful shutdown on SIGINT / SIGTERM
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self.stop()))

        try:
            loop.run_until_complete(self.start())
        except KeyboardInterrupt:
            loop.run_until_complete(self.stop())
        finally:
            loop.close()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def active_sessions(self) -> dict[str, CallSession]:
        """Return all currently active call sessions."""
        return dict(self._sessions)

    @property
    def is_running(self) -> bool:
        return self._running
