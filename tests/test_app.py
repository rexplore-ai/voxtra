"""Tests for Voxtra VoxtraApp — handler registration, routing, event dispatch."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from voxtra.app import VoxtraApp
from voxtra.ari.events import ARIEvent
from voxtra.ari.models import Channel
from voxtra.events import (
    CallEndedEvent,
    CallStartedEvent,
    DTMFEvent,
)
from voxtra.router import Router
from voxtra.session import CallSession
from voxtra.telephony.base import BaseTelephonyAdapter, EventCallback


class TestVoxtraAppConstruction:
    def test_defaults(self) -> None:
        app = VoxtraApp()
        assert app.app_name == "voxtra"
        assert app.is_running is False
        assert app.active_sessions == {}
        assert isinstance(app.router, Router)

    def test_custom_params(self) -> None:
        app = VoxtraApp(
            ari_url="http://pbx:8088",
            ari_user="admin",
            ari_password="s3cret",
            app_name="tenant-acme",
            debug=True,
        )
        assert app.ari_url == "http://pbx:8088"
        assert app.ari_user == "admin"
        assert app.ari_password == "s3cret"
        assert app.app_name == "tenant-acme"
        assert app.debug is True

    def test_custom_router(self) -> None:
        custom = Router()
        app = VoxtraApp(router=custom)
        assert app.router is custom


class TestRouteDecorator:
    def test_extension_route_registers_with_router(self) -> None:
        app = VoxtraApp()

        @app.route(extension="1000")
        async def support(call): ...

        assert any(r.extension == "1000" and r.handler is support for r in app.router.routes)

    def test_number_route_registers_with_router(self) -> None:
        app = VoxtraApp()

        @app.route(number="+265999123456")
        async def did_handler(call): ...

        assert any(
            r.number == "+265999123456" and r.handler is did_handler
            for r in app.router.routes
        )

    def test_default_decorator_registers_default(self) -> None:
        app = VoxtraApp()

        @app.default()
        async def fallback(call): ...

        assert app.router._default_handler is fallback

    def test_route_metadata_preserved(self) -> None:
        app = VoxtraApp()

        @app.route(extension="1000", metadata={"vip": True})
        async def support(call): ...

        match = [r for r in app.router.routes if r.extension == "1000"][0]
        assert match.metadata == {"vip": True}


class TestOnCallDeprecation:
    def test_on_call_bare_emits_deprecation_and_registers_default(self) -> None:
        app = VoxtraApp()
        with pytest.warns(DeprecationWarning, match="on_call is deprecated"):
            @app.on_call
            async def handle(call): ...
        assert app.router._default_handler is handle

    def test_on_call_with_extension_emits_deprecation_and_registers(self) -> None:
        app = VoxtraApp()
        with pytest.warns(DeprecationWarning, match="on_call is deprecated"):
            @app.on_call(extension="1000")
            async def support(call): ...
        assert any(
            r.extension == "1000" and r.handler is support for r in app.router.routes
        )

    def test_on_call_with_number_emits_deprecation_and_registers(self) -> None:
        app = VoxtraApp()
        with pytest.warns(DeprecationWarning):
            @app.on_call(number="+265999000000")
            async def vip(call): ...
        assert any(
            r.number == "+265999000000" and r.handler is vip for r in app.router.routes
        )


class TestHandlerResolution:
    @pytest.mark.asyncio
    async def test_resolve_by_extension(self) -> None:
        app = VoxtraApp()

        @app.route(extension="1000")
        async def support(call): ...

        handler, metadata = await app._resolve_handler("1000", "+265888111111")
        assert handler is support
        assert metadata == {}

    @pytest.mark.asyncio
    async def test_resolve_by_number(self) -> None:
        app = VoxtraApp()

        @app.route(number="+265888111111")
        async def vip(call): ...

        handler, _ = await app._resolve_handler("9999", "+265888111111")
        assert handler is vip

    @pytest.mark.asyncio
    async def test_resolve_default_fallback(self) -> None:
        app = VoxtraApp()

        @app.default()
        async def fallback(call): ...

        handler, metadata = await app._resolve_handler("unknown", "+000")
        assert handler is fallback
        # Default handler has no associated route metadata.
        assert metadata == {}

    @pytest.mark.asyncio
    async def test_resolve_extension_over_default(self) -> None:
        app = VoxtraApp()

        @app.route(extension="1000")
        async def specific(call): ...

        @app.default()
        async def fallback(call): ...

        handler, _ = await app._resolve_handler("1000", "+000")
        assert handler is specific

    @pytest.mark.asyncio
    async def test_resolve_none_when_no_handlers(self) -> None:
        app = VoxtraApp()
        handler, metadata = await app._resolve_handler("1000", "+000")
        assert handler is None
        assert metadata == {}

    @pytest.mark.asyncio
    async def test_resolve_returns_route_metadata(self) -> None:
        app = VoxtraApp()

        @app.route(extension="1000", metadata={"language": "chichewa"})
        async def support(call): ...

        handler, metadata = await app._resolve_handler("1000", "")
        assert handler is support
        assert metadata == {"language": "chichewa"}


class TestLifecycleHooks:
    def test_on_startup_registration(self) -> None:
        app = VoxtraApp()

        @app.on_startup
        async def setup(): ...

        assert len(app._on_startup) == 1

    def test_on_shutdown_registration(self) -> None:
        app = VoxtraApp()

        @app.on_shutdown
        async def teardown(): ...

        assert len(app._on_shutdown) == 1


class TestARIEventDispatch:
    @pytest.mark.asyncio
    async def test_stasis_start_creates_session(self) -> None:
        app = VoxtraApp()
        handler_calls = []

        @app.default()
        async def handle(call):
            handler_calls.append(call.id)

        event = ARIEvent(
            type="StasisStart",
            application="voxtra",
            channel=Channel(
                id="ch-test-001",
                name="PJSIP/trunk-001",
                state="Ring",
                caller_number="+265888111111",
                dialplan_exten="1000",
            ),
        )

        await app._on_stasis_start(event)

        assert "ch-test-001" in app._sessions
        session = app._sessions["ch-test-001"]
        assert session.caller_id == "+265888111111"
        assert session.called_number == "1000"

    @pytest.mark.asyncio
    async def test_stasis_start_merges_route_metadata_into_session(self) -> None:
        app = VoxtraApp()

        @app.route(extension="1000", metadata={"org_id": "acme", "vip": True})
        async def support(call): ...

        event = ARIEvent(
            type="StasisStart",
            application="voxtra",
            channel=Channel(
                id="ch-meta-test",
                caller_number="+265888111111",
                dialplan_exten="1000",
            ),
        )

        await app._on_stasis_start(event)

        session = app._sessions["ch-meta-test"]
        assert session.metadata["org_id"] == "acme"
        assert session.metadata["vip"] is True

    @pytest.mark.asyncio
    async def test_stasis_start_no_handler_hangs_up(self) -> None:
        app = VoxtraApp()
        # No handlers registered

        event = ARIEvent(
            type="StasisStart",
            application="voxtra",
            channel=Channel(id="ch-orphan", caller_number="+000", dialplan_exten="9999"),
        )

        # Should not crash, just log warning
        await app._on_stasis_start(event)
        assert "ch-orphan" not in app._sessions

    @pytest.mark.asyncio
    async def test_stasis_end_removes_session(self) -> None:
        app = VoxtraApp()

        # Manually add a session
        session = CallSession(channel_id="ch-end-test")
        app._sessions["ch-end-test"] = session

        event = ARIEvent(
            type="StasisEnd",
            channel=Channel(id="ch-end-test"),
        )

        await app._on_stasis_end(event)
        assert "ch-end-test" not in app._sessions

    @pytest.mark.asyncio
    async def test_dtmf_routes_to_session(self) -> None:
        app = VoxtraApp()

        session = CallSession(channel_id="ch-dtmf-test")
        app._sessions["ch-dtmf-test"] = session

        event = ARIEvent(
            type="ChannelDtmfReceived",
            channel=Channel(id="ch-dtmf-test"),
            digit="7",
        )

        await app._on_dtmf(event)

        # DTMF should be in the session's queue
        import asyncio
        digit = await asyncio.wait_for(session._dtmf_queue.get(), timeout=1.0)
        assert digit == "7"

    @pytest.mark.asyncio
    async def test_no_channel_events_are_safe(self) -> None:
        app = VoxtraApp()

        event = ARIEvent(type="StasisStart", channel=None)
        await app._on_stasis_start(event)  # should not raise

        event = ARIEvent(type="StasisEnd", channel=None)
        await app._on_stasis_end(event)  # should not raise

        event = ARIEvent(type="ChannelDtmfReceived", channel=None)
        await app._on_dtmf(event)  # should not raise


class _FakeAdapter(BaseTelephonyAdapter):
    """Minimal in-memory BaseTelephonyAdapter used in tests."""

    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False
        self.answered: list[str] = []
        self.hung_up: list[str] = []

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def listen(self, callback: EventCallback) -> None:
        # No-op — tests inject events via _handle_voxtra_event directly.
        return

    async def answer_call(self, channel_id: str) -> None:
        self.answered.append(channel_id)

    async def hangup_call(self, channel_id: str) -> None:
        self.hung_up.append(channel_id)

    async def transfer_call(self, channel_id: str, target: str) -> None:
        pass

    async def hold_call(self, channel_id: str) -> None:
        pass

    async def send_dtmf(self, channel_id: str, digits: str) -> None:
        pass

    async def create_media_bridge(self, channel_id: str) -> str:
        return "bridge-1"

    async def play_audio(self, channel_id: str, audio_uri: str) -> None:
        pass


class TestTelephonyAdapterWiring:
    def test_with_asterisk_classmethod_builds_adapter(self) -> None:
        from voxtra.telephony.asterisk import AsteriskAdapter

        app = VoxtraApp.with_asterisk(
            ari_url="http://pbx:8088",
            ari_user="admin",
            ari_password="secret",
            app_name="tenant-acme",
        )
        assert isinstance(app.telephony, AsteriskAdapter)
        assert app.app_name == "tenant-acme"

    def test_telephony_property_lazy_builds_asterisk_adapter(self) -> None:
        from voxtra.telephony.asterisk import AsteriskAdapter

        app = VoxtraApp(
            ari_url="http://pbx:8088",
            ari_user="admin",
            ari_password="secret",
        )
        # No adapter passed in — property returns a freshly-built Asterisk one.
        assert isinstance(app.telephony, AsteriskAdapter)
        # Subsequent access returns the same instance.
        assert app.telephony is app.telephony

    def test_constructor_accepts_custom_adapter(self) -> None:
        fake = _FakeAdapter()
        app = VoxtraApp(telephony=fake)
        assert app.telephony is fake

    @pytest.mark.asyncio
    async def test_handle_voxtra_event_creates_session_and_runs_handler(self) -> None:
        fake = _FakeAdapter()
        app = VoxtraApp(telephony=fake)
        done = asyncio.Event()
        observed: list[str] = []

        @app.route(extension="1000", metadata={"org_id": "acme"})
        async def handler(call: CallSession) -> None:
            observed.append(call.id)
            observed.append(call.metadata.get("org_id", ""))
            done.set()

        await app._handle_voxtra_event(
            CallStartedEvent(
                session_id="ch-fake-001",
                caller_id="+265888111111",
                callee_id="1000",
                direction="inbound",
            )
        )

        # The handler runs as a background task. Wait for it.
        await asyncio.wait_for(done.wait(), timeout=1.0)
        assert observed == ["ch-fake-001", "acme"]

    @pytest.mark.asyncio
    async def test_handle_voxtra_event_no_handler_drops_call(self) -> None:
        fake = _FakeAdapter()
        app = VoxtraApp(telephony=fake)

        await app._handle_voxtra_event(
            CallStartedEvent(
                session_id="ch-orphan-fake",
                caller_id="+0",
                callee_id="9999",
            )
        )
        assert "ch-orphan-fake" not in app._sessions

    @pytest.mark.asyncio
    async def test_handle_voxtra_event_dtmf_routes_to_session(self) -> None:
        fake = _FakeAdapter()
        app = VoxtraApp(telephony=fake)
        session = CallSession(channel_id="ch-dtmf-fake")
        app._sessions["ch-dtmf-fake"] = session

        await app._handle_voxtra_event(
            DTMFEvent(session_id="ch-dtmf-fake", digit="9")
        )

        digit = await asyncio.wait_for(session._dtmf_queue.get(), timeout=1.0)
        assert digit == "9"

    @pytest.mark.asyncio
    async def test_handle_voxtra_event_call_ended_removes_session(self) -> None:
        fake = _FakeAdapter()
        app = VoxtraApp(telephony=fake)
        session = CallSession(channel_id="ch-end-fake")
        app._sessions["ch-end-fake"] = session

        await app._handle_voxtra_event(
            CallEndedEvent(session_id="ch-end-fake", reason="caller_hangup")
        )

        assert "ch-end-fake" not in app._sessions
        assert session._hangup_dispatched is True

    @pytest.mark.asyncio
    async def test_stop_disconnects_adapter(self) -> None:
        fake = _FakeAdapter()
        app = VoxtraApp(telephony=fake)
        await app.stop()
        assert fake.disconnected is True


class TestFromConfig:
    def test_from_config_builds_asterisk_adapter(self) -> None:
        from voxtra.config import AsteriskConfig, TelephonyConfig, VoxtraConfig
        from voxtra.telephony.asterisk import AsteriskAdapter

        config = VoxtraConfig(
            app_name="tenant-acme",
            telephony=TelephonyConfig(
                provider="asterisk",
                asterisk=AsteriskConfig(
                    base_url="http://pbx:8088",
                    username="admin",
                    password="s3cret",
                    app_name="tenant-acme",
                ),
            ),
        )

        app = VoxtraApp.from_config(config)
        assert isinstance(app.telephony, AsteriskAdapter)
        assert app.app_name == "tenant-acme"
        assert app.telephony.client.base_url == "http://pbx:8088"
        assert app.telephony.client.username == "admin"

    def test_from_config_uses_defaults_when_asterisk_block_missing(self) -> None:
        from voxtra.config import TelephonyConfig, VoxtraConfig
        from voxtra.telephony.asterisk import AsteriskAdapter

        # No `asterisk:` block — adapter should still build from defaults.
        config = VoxtraConfig(
            app_name="default-tenant",
            telephony=TelephonyConfig(provider="asterisk"),
        )
        app = VoxtraApp.from_config(config)
        assert isinstance(app.telephony, AsteriskAdapter)
        assert app.telephony.app_name == "default-tenant"

    def test_from_config_propagates_debug(self) -> None:
        from voxtra.config import ServerConfig, VoxtraConfig

        config = VoxtraConfig(server=ServerConfig(debug=True))
        app = VoxtraApp.from_config(config)
        assert app.debug is True

    def test_from_yaml_round_trip(self, tmp_path: Path) -> None:
        from voxtra.config import (
            AsteriskConfig,
            TelephonyConfig,
            VoxtraConfig,
        )
        from voxtra.telephony.asterisk import AsteriskAdapter

        cfg = VoxtraConfig(
            app_name="yaml-tenant",
            telephony=TelephonyConfig(
                provider="asterisk",
                asterisk=AsteriskConfig(
                    base_url="http://yamlpbx:8088",
                    username="yaml-user",
                    password="yaml-pass",
                    app_name="yaml-tenant",
                ),
            ),
        )
        path = tmp_path / "voxtra.yaml"
        cfg.to_yaml(path)

        app = VoxtraApp.from_yaml(path)
        assert isinstance(app.telephony, AsteriskAdapter)
        assert app.app_name == "yaml-tenant"
        assert app.telephony.client.base_url == "http://yamlpbx:8088"


class _BlockForeverSTT:
    """Minimal BaseSTT-shaped fake whose pipeline runs forever."""

    async def transcribe_stream(self, frames):  # type: ignore[no-untyped-def]
        async for _ in frames:
            pass
        # Never yield — keep the loop alive until cancelled.
        while True:
            await asyncio.sleep(0.1)
            yield  # pragma: no cover


class _NoopLLM:
    async def respond(self, text: str):  # type: ignore[no-untyped-def]
        return None


class _NoopTTS:
    async def synthesize(self, text: str):  # type: ignore[no-untyped-def]
        if False:
            yield  # pragma: no cover
        return


class TestAutoWiredPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_not_started_without_full_ai_stack(self) -> None:
        fake_adapter = _FakeAdapter()
        app = VoxtraApp(telephony=fake_adapter)  # no stt/llm/tts

        @app.default()
        async def handle(call: CallSession) -> None:
            await asyncio.sleep(0.01)

        await app._handle_voxtra_event(
            CallStartedEvent(session_id="ch-no-pipe", caller_id="+1", callee_id="0")
        )
        await asyncio.sleep(0)
        # Session may already be cleaned up by handler; if it's still
        # around, _pipeline must be None.
        if "ch-no-pipe" in app._sessions:
            assert app._sessions["ch-no-pipe"]._pipeline is None
            assert app._sessions["ch-no-pipe"]._pipeline_task is None

    @pytest.mark.asyncio
    async def test_pipeline_started_when_stt_llm_tts_configured(self) -> None:
        from voxtra.core.pipeline import VoicePipeline

        fake_adapter = _FakeAdapter()
        app = VoxtraApp(
            telephony=fake_adapter,
            stt=_BlockForeverSTT(),  # type: ignore[arg-type]
            llm=_NoopLLM(),  # type: ignore[arg-type]
            tts=_NoopTTS(),  # type: ignore[arg-type]
        )
        observed: dict[str, CallSession] = {}
        ready = asyncio.Event()

        @app.default()
        async def handle(call: CallSession) -> None:
            observed["call"] = call
            ready.set()
            # Hold the handler open so the session isn't cleaned up
            # before our assertions run.
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise

        await app._handle_voxtra_event(
            CallStartedEvent(session_id="ch-pipe-001", caller_id="+1", callee_id="1")
        )
        await asyncio.wait_for(ready.wait(), timeout=1.0)

        session = observed["call"]
        assert isinstance(session._pipeline, VoicePipeline)
        assert session._pipeline_task is not None
        assert not session._pipeline_task.done()

        # Cleanup must cancel the pipeline task.
        await session._cleanup()
        assert session._pipeline_task is None or session._pipeline_task.done()
