"""Middleware system for Voxtra.

Middleware can intercept and transform events at various points
in the call lifecycle. Similar to ASGI middleware in web frameworks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

from voxtra.events import VoxtraEvent

# Type for the next handler in the middleware chain
NextHandler = Callable[[VoxtraEvent], Coroutine[Any, Any, VoxtraEvent | None]]


class BaseMiddleware(ABC):
    """Abstract base class for Voxtra middleware.

    Middleware wraps event processing and can:
    - Modify events before they reach the handler
    - Modify events after the handler processes them
    - Short-circuit processing by not calling next
    - Add logging, metrics, error handling, etc.
    """

    @abstractmethod
    async def process(self, event: VoxtraEvent, next_handler: NextHandler) -> VoxtraEvent | None:
        """Process an event, optionally calling the next handler.

        Args:
            event: The event to process.
            next_handler: Async callable to invoke the next middleware or final handler.

        Returns:
            The (possibly modified) event, or None to drop it.
        """
        ...


class LoggingMiddleware(BaseMiddleware):
    """Middleware that logs all events passing through the pipeline."""

    def __init__(self, logger: Any = None) -> None:
        import logging

        self._logger = logger or logging.getLogger("voxtra.events")

    async def process(self, event: VoxtraEvent, next_handler: NextHandler) -> VoxtraEvent | None:
        self._logger.debug(
            "Event [%s] session=%s",
            event.type.value,
            event.session_id,
        )
        result = await next_handler(event)
        return result


class ErrorHandlingMiddleware(BaseMiddleware):
    """Middleware that catches and logs exceptions from downstream handlers."""

    def __init__(self, logger: Any = None) -> None:
        import logging

        self._logger = logger or logging.getLogger("voxtra.errors")

    async def process(self, event: VoxtraEvent, next_handler: NextHandler) -> VoxtraEvent | None:
        try:
            return await next_handler(event)
        except Exception as exc:
            self._logger.exception(
                "Error processing event [%s] session=%s: %s",
                event.type.value,
                event.session_id,
                exc,
            )
            return None
