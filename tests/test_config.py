"""Tests for Voxtra configuration system."""

from __future__ import annotations

import tempfile

import pytest

from voxtra.config import (
    AIConfig,
    AsteriskConfig,
    LLMConfig,
    MediaConfig,
    TelephonyConfig,
    VoxtraConfig,
)
from voxtra.types import AudioCodec, MediaTransportType


class TestAsteriskConfig:
    def test_default_values(self) -> None:
        config = AsteriskConfig()
        assert config.base_url == "http://localhost:8088"
        assert config.username == "asterisk"
        assert config.app_name == "voxtra"

    def test_websocket_url_derived(self) -> None:
        config = AsteriskConfig(base_url="http://myhost:8088", app_name="myapp")
        assert config.websocket_url == "ws://myhost:8088/ari/events?app=myapp"

    def test_websocket_url_explicit(self) -> None:
        config = AsteriskConfig(websocket_url="ws://custom:9090/events")
        assert config.websocket_url == "ws://custom:9090/events"


class TestMediaConfig:
    def test_defaults(self) -> None:
        config = MediaConfig()
        assert config.transport == MediaTransportType.WEBSOCKET
        assert config.codec == AudioCodec.ULAW
        assert config.sample_rate == 8000
        assert config.channels == 1
        assert config.frame_duration_ms == 20


class TestAIConfig:
    def test_default_providers(self) -> None:
        config = AIConfig()
        assert config.stt.provider == "deepgram"
        assert config.tts.provider == "elevenlabs"
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o"

    def test_custom_system_prompt(self) -> None:
        config = AIConfig(llm=LLMConfig(system_prompt="You are a sales agent."))
        assert config.llm.system_prompt == "You are a sales agent."


class TestVoxtraConfig:
    def test_default_construction(self) -> None:
        config = VoxtraConfig()
        assert config.app_name == "voxtra"
        assert config.telephony.provider == "asterisk"

    def test_from_yaml(self) -> None:
        yaml_content = """
app_name: test-app
telephony:
  provider: asterisk
  asterisk:
    base_url: http://myhost:8088
    username: admin
    password: secret123
    app_name: testapp
ai:
  stt:
    provider: deepgram
    model: nova-2
  llm:
    provider: openai
    model: gpt-4o
    system_prompt: "Test prompt"
  tts:
    provider: elevenlabs
routes:
  - extension: "1000"
    agent: support
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = VoxtraConfig.from_yaml(f.name)
            assert config.app_name == "test-app"
            assert config.telephony.asterisk is not None
            assert config.telephony.asterisk.base_url == "http://myhost:8088"
            assert config.telephony.asterisk.username == "admin"
            assert config.ai.llm.system_prompt == "Test prompt"
            assert len(config.routes) == 1
            assert config.routes[0].extension == "1000"

    def test_from_yaml_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            VoxtraConfig.from_yaml("/nonexistent/path.yaml")

    def test_to_yaml_roundtrip(self) -> None:
        config = VoxtraConfig(
            app_name="roundtrip-test",
            telephony=TelephonyConfig(
                provider="asterisk",
                asterisk=AsteriskConfig(base_url="http://test:8088"),
            ),
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config.to_yaml(f.name)
            loaded = VoxtraConfig.from_yaml(f.name)
            assert loaded.app_name == "roundtrip-test"
            assert loaded.telephony.provider == "asterisk"
