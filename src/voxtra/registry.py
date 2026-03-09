"""Provider registry for Voxtra.

A central registry that maps provider names to their implementation classes.
This enables a plugin-like architecture where new providers can register
themselves without modifying core framework code.

Usage for built-in providers::

    from voxtra.registry import registry

    @registry.register_stt("deepgram")
    class DeepgramSTT(BaseSTT):
        ...

Usage for third-party providers::

    # In your package's __init__.py or entry point:
    from voxtra.registry import registry
    from my_package.whisper_stt import WhisperSTT

    registry.register_stt("whisper")(WhisperSTT)

Resolving a provider from config::

    stt_cls = registry.resolve_stt("deepgram")
    stt = stt_cls(config=stt_config)
"""

from __future__ import annotations

import logging
from typing import Any

from voxtra.exceptions import ConfigurationError

logger = logging.getLogger("voxtra.registry")


class ProviderRegistry:
    """Central registry for all Voxtra providers.

    Manages mappings from provider name strings (e.g., "deepgram", "openai")
    to their concrete implementation classes. Supports STT, TTS, LLM,
    VAD, telephony, and media transport providers.
    """

    def __init__(self) -> None:
        self._stt: dict[str, type[Any]] = {}
        self._tts: dict[str, type[Any]] = {}
        self._llm: dict[str, type[Any]] = {}
        self._vad: dict[str, type[Any]] = {}
        self._telephony: dict[str, type[Any]] = {}
        self._media: dict[str, type[Any]] = {}

    # ------------------------------------------------------------------
    # Registration decorators / methods
    # ------------------------------------------------------------------

    def register_stt(self, name: str) -> Any:
        """Register an STT provider class.

        Can be used as a decorator::

            @registry.register_stt("deepgram")
            class DeepgramSTT(BaseSTT):
                ...

        Or called directly::

            registry.register_stt("whisper")(WhisperSTT)
        """
        def decorator(cls: type[Any]) -> type[Any]:
            self._stt[name] = cls
            logger.debug("Registered STT provider: %s -> %s", name, cls.__name__)
            return cls
        return decorator

    def register_tts(self, name: str) -> Any:
        """Register a TTS provider class."""
        def decorator(cls: type[Any]) -> type[Any]:
            self._tts[name] = cls
            logger.debug("Registered TTS provider: %s -> %s", name, cls.__name__)
            return cls
        return decorator

    def register_llm(self, name: str) -> Any:
        """Register an LLM/Agent provider class."""
        def decorator(cls: type[Any]) -> type[Any]:
            self._llm[name] = cls
            logger.debug("Registered LLM provider: %s -> %s", name, cls.__name__)
            return cls
        return decorator

    def register_vad(self, name: str) -> Any:
        """Register a VAD provider class."""
        def decorator(cls: type[Any]) -> type[Any]:
            self._vad[name] = cls
            logger.debug("Registered VAD provider: %s -> %s", name, cls.__name__)
            return cls
        return decorator

    def register_telephony(self, name: str) -> Any:
        """Register a telephony adapter class."""
        def decorator(cls: type[Any]) -> type[Any]:
            self._telephony[name] = cls
            logger.debug("Registered telephony adapter: %s -> %s", name, cls.__name__)
            return cls
        return decorator

    def register_media(self, name: str) -> Any:
        """Register a media transport class."""
        def decorator(cls: type[Any]) -> type[Any]:
            self._media[name] = cls
            logger.debug("Registered media transport: %s -> %s", name, cls.__name__)
            return cls
        return decorator

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_stt(self, name: str) -> type[Any]:
        """Resolve an STT provider class by name."""
        return self._resolve("STT", self._stt, name)

    def resolve_tts(self, name: str) -> type[Any]:
        """Resolve a TTS provider class by name."""
        return self._resolve("TTS", self._tts, name)

    def resolve_llm(self, name: str) -> type[Any]:
        """Resolve an LLM/Agent provider class by name."""
        return self._resolve("LLM", self._llm, name)

    def resolve_vad(self, name: str) -> type[Any]:
        """Resolve a VAD provider class by name."""
        return self._resolve("VAD", self._vad, name)

    def resolve_telephony(self, name: str) -> type[Any]:
        """Resolve a telephony adapter class by name."""
        return self._resolve("telephony", self._telephony, name)

    def resolve_media(self, name: str) -> type[Any]:
        """Resolve a media transport class by name."""
        return self._resolve("media", self._media, name)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_stt(self) -> list[str]:
        """List all registered STT provider names."""
        return list(self._stt.keys())

    def list_tts(self) -> list[str]:
        """List all registered TTS provider names."""
        return list(self._tts.keys())

    def list_llm(self) -> list[str]:
        """List all registered LLM provider names."""
        return list(self._llm.keys())

    def list_vad(self) -> list[str]:
        """List all registered VAD provider names."""
        return list(self._vad.keys())

    def list_telephony(self) -> list[str]:
        """List all registered telephony adapter names."""
        return list(self._telephony.keys())

    def list_media(self) -> list[str]:
        """List all registered media transport names."""
        return list(self._media.keys())

    def list_all(self) -> dict[str, list[str]]:
        """List all registered providers grouped by type."""
        return {
            "stt": self.list_stt(),
            "tts": self.list_tts(),
            "llm": self.list_llm(),
            "vad": self.list_vad(),
            "telephony": self.list_telephony(),
            "media": self.list_media(),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(self, category: str, store: dict[str, type[Any]], name: str) -> type[Any]:
        """Look up a provider class, raising a clear error if not found."""
        cls = store.get(name)
        if cls is not None:
            return cls

        available = ", ".join(sorted(store.keys())) or "(none)"
        raise ConfigurationError(
            f"Unknown {category} provider: '{name}'. "
            f"Available: {available}. "
            f"Make sure the provider package is installed "
            f"(e.g., pip install voxtra[{name}])."
        )


# Global singleton — import this in provider modules and app.py
registry = ProviderRegistry()
