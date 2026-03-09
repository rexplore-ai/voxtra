"""Tests for Voxtra provider registry system."""

from __future__ import annotations

import pytest

from voxtra.exceptions import ConfigurationError
from voxtra.registry import ProviderRegistry


class TestProviderRegistry:
    """Test the ProviderRegistry class."""

    def test_register_and_resolve_stt(self) -> None:
        reg = ProviderRegistry()

        @reg.register_stt("test_stt")
        class TestSTT:
            pass

        assert reg.resolve_stt("test_stt") is TestSTT

    def test_register_and_resolve_tts(self) -> None:
        reg = ProviderRegistry()

        @reg.register_tts("test_tts")
        class TestTTS:
            pass

        assert reg.resolve_tts("test_tts") is TestTTS

    def test_register_and_resolve_llm(self) -> None:
        reg = ProviderRegistry()

        @reg.register_llm("test_llm")
        class TestLLM:
            pass

        assert reg.resolve_llm("test_llm") is TestLLM

    def test_register_and_resolve_vad(self) -> None:
        reg = ProviderRegistry()

        @reg.register_vad("test_vad")
        class TestVAD:
            pass

        assert reg.resolve_vad("test_vad") is TestVAD

    def test_register_and_resolve_telephony(self) -> None:
        reg = ProviderRegistry()

        @reg.register_telephony("test_tel")
        class TestTelephony:
            pass

        assert reg.resolve_telephony("test_tel") is TestTelephony

    def test_register_and_resolve_media(self) -> None:
        reg = ProviderRegistry()

        @reg.register_media("test_media")
        class TestMedia:
            pass

        assert reg.resolve_media("test_media") is TestMedia

    def test_resolve_unknown_raises_error(self) -> None:
        reg = ProviderRegistry()

        with pytest.raises(ConfigurationError, match="Unknown STT provider: 'nonexistent'"):
            reg.resolve_stt("nonexistent")

    def test_resolve_error_lists_available(self) -> None:
        reg = ProviderRegistry()

        @reg.register_stt("alpha")
        class Alpha:
            pass

        @reg.register_stt("beta")
        class Beta:
            pass

        with pytest.raises(ConfigurationError, match="Available: alpha, beta"):
            reg.resolve_stt("gamma")

    def test_list_providers(self) -> None:
        reg = ProviderRegistry()

        @reg.register_stt("deepgram")
        class DG:
            pass

        @reg.register_tts("elevenlabs")
        class EL:
            pass

        assert reg.list_stt() == ["deepgram"]
        assert reg.list_tts() == ["elevenlabs"]
        assert reg.list_llm() == []

    def test_list_all(self) -> None:
        reg = ProviderRegistry()

        @reg.register_stt("a")
        class A:
            pass

        @reg.register_llm("b")
        class B:
            pass

        result = reg.list_all()
        assert result["stt"] == ["a"]
        assert result["llm"] == ["b"]
        assert result["tts"] == []
        assert result["vad"] == []
        assert result["telephony"] == []
        assert result["media"] == []

    def test_direct_registration(self) -> None:
        """Test non-decorator registration style."""
        reg = ProviderRegistry()

        class MySTT:
            pass

        reg.register_stt("my_stt")(MySTT)
        assert reg.resolve_stt("my_stt") is MySTT

    def test_global_registry_has_builtins(self) -> None:
        """Verify that importing provider modules registers them in the global registry."""
        # Import a built-in provider to trigger registration
        import voxtra.ai.vad.base  # noqa: F401
        from voxtra.registry import registry

        assert "energy" in registry.list_vad()
