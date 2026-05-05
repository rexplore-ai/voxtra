"""Tests for ARIClient.originate() parameter shaping.

The originate endpoint supports two routing modes — Stasis-app
routing and dialplan routing — and the client must shape the
``/ari/channels`` POST params correctly for each. Channel variables
must travel in the request *body*, not the query string, per the
ARI spec — see test_originate_variables_go_in_body for the regression.
"""

from __future__ import annotations

from typing import Any

import pytest

from voxtra.ari.client import ARIClient


class _CapturingClient(ARIClient):
    """Test double that records the params + body sent to ``_post``."""

    def __init__(self, app_name: str = "voxtra") -> None:
        super().__init__(
            base_url="http://example/ari",
            username="u",
            password="p",
            app_name=app_name,
        )
        self.last_path: str | None = None
        self.last_params: dict[str, Any] | None = None
        self.last_body: Any = None

    async def _post(  # type: ignore[override]
        self,
        path: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        self.last_path = path
        self.last_params = params or {}
        self.last_body = json
        return {"id": "ch-test"}


@pytest.mark.asyncio
async def test_originate_defaults_to_stasis_routing() -> None:
    client = _CapturingClient(app_name="voxtra-tenant-acme")
    await client.originate("PJSIP/+265@trunk", caller_id="+265111", timeout=20)

    assert client.last_path == "/ari/channels"
    assert client.last_params is not None
    assert client.last_params["app"] == "voxtra-tenant-acme"
    assert client.last_params["endpoint"] == "PJSIP/+265@trunk"
    assert client.last_params["callerId"] == "+265111"
    assert client.last_params["timeout"] == 20
    # No dialplan params when running in Stasis mode.
    assert "context" not in client.last_params
    assert "extension" not in client.last_params
    # No body when no variables.
    assert client.last_body is None


@pytest.mark.asyncio
async def test_originate_dialplan_routing_no_app() -> None:
    """Dialplan-mode: context set, app must NOT be present."""
    client = _CapturingClient()
    await client.originate(
        "PJSIP/+265@trunk",
        context="from-trunk",
        extension="+265111",
        variables={"LUSO8_CALL_ID": "abc"},
    )

    assert client.last_params is not None
    assert client.last_params["context"] == "from-trunk"
    assert client.last_params["extension"] == "+265111"
    assert client.last_params["priority"] == 1  # default
    assert "app" not in client.last_params


@pytest.mark.asyncio
async def test_originate_variables_go_in_body() -> None:
    """Regression: channel variables MUST travel in the request body, not
    the URL query string. ARI's POST /channels expects
    ``{"variables": {...}}`` at the body root; sending variables as a
    query parameter is silently ignored by Asterisk, which broke
    channel-variable propagation in 0.3.0 / 0.3.1."""
    client = _CapturingClient()
    await client.originate(
        "PJSIP/+265@trunk",
        context="from-trunk",
        extension="+265111",
        variables={
            "LUSO8_CALL_ID": "call-abc",
            "LUSO8_VOICE_AGENT_ID": "agent-xyz",
            "LUSO8_OBJECTIVE": "Confirm appointment",
        },
    )

    # Body shape — single-wrapped under the "variables" key.
    assert client.last_body == {
        "variables": {
            "LUSO8_CALL_ID": "call-abc",
            "LUSO8_VOICE_AGENT_ID": "agent-xyz",
            "LUSO8_OBJECTIVE": "Confirm appointment",
        }
    }
    # And NOT in the query params.
    assert client.last_params is not None
    assert "variables" not in client.last_params


@pytest.mark.asyncio
async def test_originate_no_body_when_no_variables() -> None:
    client = _CapturingClient()
    await client.originate(
        "PJSIP/+265@trunk",
        context="from-trunk",
        extension="+265111",
    )
    assert client.last_body is None


@pytest.mark.asyncio
async def test_originate_dialplan_extension_defaults_to_s() -> None:
    client = _CapturingClient()
    await client.originate("PJSIP/x@trunk", context="from-trunk")
    assert client.last_params is not None
    assert client.last_params["extension"] == "s"


@pytest.mark.asyncio
async def test_originate_with_explicit_channel_id() -> None:
    client = _CapturingClient()
    await client.originate(
        "PJSIP/x@trunk",
        context="from-trunk",
        channel_id="my-channel-uuid",
    )
    assert client.last_params is not None
    assert client.last_params["channelId"] == "my-channel-uuid"


@pytest.mark.asyncio
async def test_originate_explicit_app_with_dialplan_passes_both() -> None:
    """If caller passes app= AND context=, both go through unchanged."""
    client = _CapturingClient()
    await client.originate(
        "PJSIP/x@trunk",
        app="my-stasis-app",
        context="from-trunk",
        extension="123",
    )
    assert client.last_params is not None
    assert client.last_params["app"] == "my-stasis-app"
    assert client.last_params["context"] == "from-trunk"
