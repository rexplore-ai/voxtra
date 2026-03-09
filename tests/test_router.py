"""Tests for Voxtra call routing system."""

from __future__ import annotations

import pytest

from voxtra.exceptions import RouteNotFoundError
from voxtra.router import Route, Router
from voxtra.session import CallSession


# --- Route matching ---

class TestRoute:
    def test_match_by_extension(self) -> None:
        async def handler(s: CallSession) -> None: ...

        route = Route(handler=handler, extension="1000")
        assert route.matches(extension="1000") is True
        assert route.matches(extension="2000") is False

    def test_match_by_number(self) -> None:
        async def handler(s: CallSession) -> None: ...

        route = Route(handler=handler, number="+265888111111")
        assert route.matches(number="+265888111111") is True
        assert route.matches(number="+265888222222") is False

    def test_match_wildcard_number(self) -> None:
        async def handler(s: CallSession) -> None: ...

        route = Route(handler=handler, number="+265*")
        assert route.matches(number="+265888111111") is True
        assert route.matches(number="+1555000000") is False

    def test_no_match_empty(self) -> None:
        async def handler(s: CallSession) -> None: ...

        route = Route(handler=handler, extension="1000")
        assert route.matches() is False


# --- Router ---

class TestRouter:
    @pytest.mark.asyncio
    async def test_route_decorator(self) -> None:
        router = Router()

        @router.route(extension="1000")
        async def support(session: CallSession) -> None: ...

        assert len(router.routes) == 1
        assert router.routes[0].extension == "1000"
        assert router.routes[0].name == "support"

    @pytest.mark.asyncio
    async def test_resolve_by_extension(self) -> None:
        router = Router()

        @router.route(extension="1000")
        async def support(session: CallSession) -> None: ...

        @router.route(extension="2000")
        async def sales(session: CallSession) -> None: ...

        handler = await router.resolve(extension="1000")
        assert handler is support

        handler = await router.resolve(extension="2000")
        assert handler is sales

    @pytest.mark.asyncio
    async def test_resolve_by_number(self) -> None:
        router = Router()

        @router.route(number="+265888111111")
        async def direct_line(session: CallSession) -> None: ...

        handler = await router.resolve(number="+265888111111")
        assert handler is direct_line

    @pytest.mark.asyncio
    async def test_resolve_default(self) -> None:
        router = Router()

        @router.default()
        async def fallback(session: CallSession) -> None: ...

        handler = await router.resolve(extension="9999")
        assert handler is fallback

    @pytest.mark.asyncio
    async def test_resolve_not_found(self) -> None:
        router = Router()

        with pytest.raises(RouteNotFoundError):
            await router.resolve(extension="9999")

    @pytest.mark.asyncio
    async def test_dispatch_rule(self) -> None:
        router = Router()

        async def chichewa_handler(session: CallSession) -> None: ...

        async def language_dispatch(call_info: dict) -> None:
            if call_info.get("language") == "chichewa":
                return chichewa_handler
            return None

        router.add_dispatch_rule(language_dispatch)

        handler = await router.resolve(
            extension="1000",
            call_info={"language": "chichewa"},
        )
        assert handler is chichewa_handler

    @pytest.mark.asyncio
    async def test_multiple_routes(self) -> None:
        router = Router()

        @router.route(extension="1000", name="support")
        async def support(session: CallSession) -> None: ...

        @router.route(extension="2000", name="sales")
        async def sales(session: CallSession) -> None: ...

        @router.route(number="+265888000000", name="direct")
        async def direct(session: CallSession) -> None: ...

        assert len(router.routes) == 3
