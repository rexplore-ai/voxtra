"""Tests for Voxtra VoxtraApp — handler registration, routing, event dispatch."""

from __future__ import annotations

import pytest

from voxtra.app import VoxtraApp
from voxtra.ari.events import ARIEvent
from voxtra.ari.models import Channel
from voxtra.session import CallSession


class TestVoxtraAppConstruction:
    def test_defaults(self) -> None:
        app = VoxtraApp()
        assert app.app_name == "voxtra"
        assert app.is_running is False
        assert app.active_sessions == {}

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


class TestOnCallDecorator:
    def test_default_handler(self) -> None:
        app = VoxtraApp()

        @app.on_call
        async def handle(call): ...

        assert app._default_handler is handle

    def test_extension_handler(self) -> None:
        app = VoxtraApp()

        @app.on_call(extension="1000")
        async def support(call): ...

        assert "1000" in app._handlers
        assert app._handlers["1000"] is support

    def test_number_handler(self) -> None:
        app = VoxtraApp()

        @app.on_call(number="+265999123456")
        async def did_handler(call): ...

        assert "num:+265999123456" in app._handlers

    def test_multiple_handlers(self) -> None:
        app = VoxtraApp()

        @app.on_call(extension="1000")
        async def support(call): ...

        @app.on_call(extension="2000")
        async def sales(call): ...

        @app.on_call
        async def fallback(call): ...

        assert len(app._handlers) == 2
        assert app._default_handler is fallback


class TestHandlerResolution:
    def test_resolve_by_extension(self) -> None:
        app = VoxtraApp()

        @app.on_call(extension="1000")
        async def support(call): ...

        handler = app._resolve_handler("1000", "+265888111111")
        assert handler is support

    def test_resolve_by_number(self) -> None:
        app = VoxtraApp()

        @app.on_call(number="+265888111111")
        async def vip(call): ...

        handler = app._resolve_handler("9999", "+265888111111")
        assert handler is vip

    def test_resolve_default_fallback(self) -> None:
        app = VoxtraApp()

        @app.on_call
        async def fallback(call): ...

        handler = app._resolve_handler("unknown", "+000")
        assert handler is fallback

    def test_resolve_extension_over_default(self) -> None:
        app = VoxtraApp()

        @app.on_call(extension="1000")
        async def specific(call): ...

        @app.on_call
        async def fallback(call): ...

        handler = app._resolve_handler("1000", "+000")
        assert handler is specific

    def test_resolve_none_when_no_handlers(self) -> None:
        app = VoxtraApp()
        handler = app._resolve_handler("1000", "+000")
        assert handler is None


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

        @app.on_call
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
