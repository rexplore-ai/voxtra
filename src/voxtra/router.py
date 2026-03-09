"""Call routing system for Voxtra.

The Router maps incoming calls to handler functions based on
extension, phone number, or custom matching logic. Inspired
by FastAPI's decorator-based routing pattern.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from voxtra.exceptions import RouteNotFoundError

logger = logging.getLogger("voxtra.router")

# Type alias for an async call handler: async def handler(session) -> None
CallHandler = Callable[..., Coroutine[Any, Any, None]]


@dataclass
class Route:
    """A single routing rule mapping a call pattern to a handler."""

    handler: CallHandler
    extension: str | None = None
    number: str | None = None
    name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(self, *, extension: str = "", number: str = "") -> bool:
        """Check whether an incoming call matches this route."""
        if self.extension and extension:
            return self.extension == extension
        if self.number and number:
            # Support wildcard prefix matching (e.g. "+265*")
            if self.number.endswith("*"):
                return number.startswith(self.number[:-1])
            return self.number == number
        return False


class Router:
    """Routes incoming calls to the appropriate async handler.

    Usage::

        router = Router()

        @router.route(extension="1000")
        async def support_call(session):
            ...

        @router.route(number="+265888111111")
        async def direct_line(session):
            ...

    The router also supports a default fallback handler and
    dispatcher rules for more complex routing logic.
    """

    def __init__(self) -> None:
        self._routes: list[Route] = []
        self._default_handler: CallHandler | None = None
        self._dispatch_rules: list[Callable[..., Coroutine[Any, Any, CallHandler | None]]] = []

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
    ) -> Callable[[CallHandler], CallHandler]:
        """Decorator to register a call handler for a given extension or number.

        Args:
            extension: Asterisk extension to match (e.g. "1000").
            number: Phone number to match (e.g. "+265888111111").
            name: Optional human-readable name for the route.
            metadata: Arbitrary metadata attached to the route.
        """

        def decorator(func: CallHandler) -> CallHandler:
            route = Route(
                handler=func,
                extension=extension,
                number=number,
                name=name or func.__name__,
                metadata=metadata or {},
            )
            self._routes.append(route)
            logger.info(
                "Registered route '%s' (extension=%s, number=%s)",
                route.name,
                extension,
                number,
            )
            return func

        return decorator

    def default(self) -> Callable[[CallHandler], CallHandler]:
        """Decorator to register a default (fallback) handler."""

        def decorator(func: CallHandler) -> CallHandler:
            self._default_handler = func
            logger.info("Registered default handler: %s", func.__name__)
            return func

        return decorator

    def add_dispatch_rule(
        self,
        rule: Callable[..., Coroutine[Any, Any, CallHandler | None]],
    ) -> None:
        """Register a dynamic dispatch rule.

        A dispatch rule is an async function that receives call metadata
        and returns a handler (or None to skip). Rules are evaluated in
        order; the first non-None result wins.

        Example::

            async def language_dispatch(call_info: dict) -> CallHandler | None:
                if call_info.get("language") == "chichewa":
                    return chichewa_agent
                return None

            router.add_dispatch_rule(language_dispatch)
        """
        self._dispatch_rules.append(rule)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def resolve(
        self,
        *,
        extension: str = "",
        number: str = "",
        call_info: dict[str, Any] | None = None,
    ) -> CallHandler:
        """Find the handler for an incoming call.

        Resolution order:
        1. Dynamic dispatch rules
        2. Static routes (extension / number match)
        3. Default handler

        Raises:
            RouteNotFoundError: If no route matches and no default is set.
        """
        # 1. Try dispatch rules
        if call_info:
            for rule in self._dispatch_rules:
                handler = await rule(call_info)
                if handler is not None:
                    return handler

        # 2. Try static routes
        for route in self._routes:
            if route.matches(extension=extension, number=number):
                logger.debug(
                    "Matched route '%s' for extension=%s number=%s",
                    route.name,
                    extension,
                    number,
                )
                return route.handler

        # 3. Fallback
        if self._default_handler is not None:
            logger.debug("Using default handler")
            return self._default_handler

        raise RouteNotFoundError(
            f"No route found for extension={extension!r}, number={number!r}"
        )

    @property
    def routes(self) -> list[Route]:
        """Return a copy of all registered routes."""
        return list(self._routes)
