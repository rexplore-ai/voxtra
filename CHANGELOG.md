# Changelog

All notable changes to Voxtra will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-05-05

This release closes the three remaining roadmap items needed for clean
integration with downstream consumers: webhook-based event emission,
pluggable recording sinks, and live Asterisk reload.

### Added
- **`BackendWebhook`** (`voxtra.webhooks.BackendWebhook`) — fire-and-forget HTTP emitter that POSTs every `VoxtraEvent` to a configured URL. Supports HMAC-SHA256 signing via `signing_secret`, per-event-type filtering via `events`, and exponential-backoff retries on 5xx / transport errors. 4xx responses are not retried. New `WebhookConfig` and `BackendConfig` types in `voxtra.config`. `VoxtraApp(webhook=...)` constructor parameter; `VoxtraApp.from_config()` auto-builds the emitter when `config.backend.webhook.url` is set. Webhook delivery is best-effort and never raises into the call pipeline.
- **`RecordingSink` abstraction** (`voxtra.recording`) — pluggable destinations for finished call recordings. New `RecordingSink` ABC with a single `on_recording_complete(metadata)` method. Concrete sinks: `LocalFileSink` (default no-op), `WebhookSink` (POST recording metadata to a URL with optional HMAC signing), and `CompositeSink` (fan-out to multiple sinks with per-sink error isolation). `VoxtraApp(recording_sink=...)` propagates a default to every session; `session.record_start(sink=...)` overrides per-call. `RecordingMetadata` dataclass carries `session_id`, `name`, `file_path`, `duration_seconds`, and `format`.
- **`ARIClient.reload_module(name)`** — issues `PUT /ari/asterisk/modules/{module}` for live config reload. New `ARIClient.list_modules()` for introspection.
- **Real `TenantProvisioner.reload_asterisk(ari)`** — reloads `res_pjsip.so`, `pbx_config.so`, and `res_ari.so` (the three modules whose configs the provisioner touches) via ARI. Per-module failures are logged and skipped rather than raising — partial reloads are valid.
- **`ARIClient.originate()` dialplan routing** — `originate(endpoint, context=, extension=, priority=, channel_id=)` now supports the dialplan-routing mode of ARI's `/channels` API. Pass `context=` to enter the dialplan instead of a Stasis app. Required for downstream consumers that drive Asterisk via channel variables (`LUSO8_CALL_ID`, etc) read from existing dialplan logic.

### Changed
- **`CallSession._default_recording_sink`** — populated by `VoxtraApp` when `recording_sink=` is configured. `record_start` falls back to this when no per-call sink is provided.
- **Webhook events emitted from ARI dispatch path** — `_on_stasis_start`, `_on_stasis_end`, `_on_dtmf`, and `_on_channel_hangup` now also fire the webhook in addition to the session queue, mirroring the behaviour of the non-Asterisk `_handle_voxtra_event` path.

### Tests
- 199 tests (was 179). New: `tests/test_webhooks.py` (10 tests), `tests/test_recording.py` (7 tests). Expanded: `tests/test_provisioning.py` (3 new reload tests).

## [0.3.0] - 2026-05-04

This release wires the previously-disconnected abstractions into the public API
so the documented mental model matches reality. It is intended as the
integration target for downstream consumers (e.g. Luso8's Asterisk plumbing).

### Added
- **`@app.route(extension=, number=, metadata=)` and `@app.default()`** — first-class routing decorators on `VoxtraApp`. Route metadata is merged into `session.metadata` so handlers can read tenant/org context populated by the router. `app.default_route` alias preserved for the existing examples.
- **`BaseTelephonyAdapter` is now used end-to-end** — `VoxtraApp(telephony=...)` accepts any adapter; `VoxtraApp.with_asterisk(...)` classmethod for the common case. `AsteriskAdapter` (alias of `AsteriskARIAdapter`) wraps `ARIClient` and translates ARI events to `VoxtraEvent`s. New `VoxtraApp._handle_voxtra_event` provides backend-agnostic dispatch for non-Asterisk adapters.
- **`VoxtraApp.from_yaml(path)` / `from_config(VoxtraConfig)`** — build an app from a YAML config file. Resolves the telephony adapter from the registry. Fixes `voxtra start` which was previously broken.
- **AudioSocket hangup propagation** — `AudioSocketConnection` now fires an `on_hangup` callback exactly once on `FRAME_HANGUP`, EOF, or error. `CallSession` bridges this to a `CALL_ENDED` event and dedupes against ARI's `StasisEnd` so callbacks don't double-fire when the media leg drops before the signalling channel.
- **Auto-wired `VoicePipeline`** — `VoxtraApp(stt=, llm=, tts=, vad=)` spawns a pipeline per session as a background task. New `voxtra.media.session_transport.CallSessionMediaTransport` bridges the previously-incompatible `AudioChunk` and `AudioFrame` stacks. Pipeline events route back into the session queue so handlers can wait on them.
- **`session.say(text)`, `session.listen(timeout=)`, `session.agent`** — high-level convenience API on `CallSession`. `AgentClient` maintains a per-session conversation history. All three raise a clear `RuntimeError` when no AI pipeline is configured.
- **`AudioFrame.from_chunk()`, `AudioFrame.to_chunk()`, `AudioFrame.to_codec()`** — explicit interop with the AudioSocket `AudioChunk` stack. `to_codec()` generalises the existing `to_pcm_s16le()` to any supported codec.

### Changed
- **`VoxtraApp.__init__`** now accepts `router=`, `telephony=`, `stt=`, `llm=`, `tts=`, `vad=` keyword arguments. The legacy `ari_url`/`ari_user`/`ari_password` form still works — an `AsteriskAdapter` is built lazily on first access.
- **CLI `voxtra start`** uses `VoxtraApp.from_yaml(path)` instead of the broken `VoxtraApp(config=...)` call.
- **Public quick-start example** in `voxtra/__init__.py` updated to `@app.default()` (was `@app.on_call`).

### Deprecated
- **`@app.on_call`** — emits `DeprecationWarning`. Use `@app.route(...)` or `@app.default()` instead. The decorator still works for one more minor version.

### Fixed
- **CLI `TypeError` on every start** — `voxtra start -c voxtra.yaml` was unconditionally crashing because the constructor had no `config=` kwarg.
- **Session hang when AudioSocket disconnects before ARI** — without ARI's `StasisEnd`, sessions previously hung forever. The session now tears down on the first signal from either source.
- **`bundled examples/sales_bot/main.py` and `examples/support_bot/main.py`** crashed on import because they referenced API that didn't exist (`VoxtraApp.from_yaml`, `@app.route`, `@app.default_route`, `session.say`, `session.listen`, `session.agent`). All of these are now real.

### Tests
- 179 tests (was 125). New: `tests/test_asterisk_adapter.py`, `tests/test_session_transport.py`. Expanded: `tests/test_app.py`, `tests/test_audiosocket.py`, `tests/test_session.py`.

## [0.1.0b1] - 2026-03-09

### Added
- **Provider Registry** — Plugin architecture for all provider types (STT, TTS, LLM, VAD, telephony, media). Providers self-register via `@registry.register_*()` decorators. Third-party packages can register without modifying core code.
- **Documentation**
  - `docs/glossary.md` — Full definitions for 23+ abbreviations and terms (SIP, RTP, PCM, μ-law, DTMF, ARI, STT, TTS, LLM, VAD, etc.)
  - `docs/media-guide.md` — Deep dive into audio concepts: codecs, framing, sampling, AudioFrame design, jitter buffering, WebSocket vs RTP trade-offs
  - `docs/telephony-guide.md` — Deep dive into telephony: SIP signaling/media split, ARI architecture, Stasis model, channels/bridges/external media, DTMF, Asterisk configuration
- **Open Source Community Files**
  - Full Apache 2.0 LICENSE text
  - CODE_OF_CONDUCT.md (Contributor Covenant v2.1)
  - SECURITY.md with vulnerability reporting policy
  - GitHub issue templates (bug report, feature request)
  - Pull request template with checklist
  - FUNDING.yml (GitHub Sponsors)
- **CI/CD**
  - GitHub Actions CI workflow (lint, typecheck, tests on Python 3.11/3.12)
  - GitHub Actions publish workflow (TestPyPI + PyPI via trusted OIDC)
- **Tests** — 12 new tests for the provider registry (62 total)

### Changed
- `app.py` — Replaced hardcoded `if/elif` provider factories with registry-based resolution
- All providers now decorated with `@registry.register_*()` for auto-registration
- Updated `docs/architecture.md` with provider registry section and links to new guides

### Fixed
- **49 ruff lint errors** resolved:
  - Unused imports removed across 8 files
  - `str, Enum` → `StrEnum` migrations
  - Import sorting (`I001`) fixed
  - `typing` → `collections.abc` for `AsyncIterator`, `Callable`, `Coroutine`
  - `asyncio.TimeoutError` → builtin `TimeoutError`
  - Variable naming (`N806`) in audio codec functions
  - Unused variable assignment in Asterisk adapter

## [0.1.0a1] - 2026-03-09

### Added
- Initial pre-release of Voxtra framework
- **Core** — VoxtraApp, Router, CallSession, Events, Config, Middleware
- **AI Providers** — BaseSTT (Deepgram), BaseTTS (ElevenLabs), BaseAgent (OpenAI), BaseVAD (EnergyVAD)
- **Telephony** — BaseTelephonyAdapter, AsteriskARIAdapter (full), LiveKitAdapter (stub)
- **Media** — AudioFrame, WebSocketMediaTransport, AudioBuffer, codec conversion (μ-law/A-law/PCM)
- **Pipeline** — VoicePipeline (STT→LLM→TTS with barge-in detection)
- **CLI** — `voxtra start`, `voxtra init`, `voxtra info`, `voxtra check`
- **Examples** — Basic support bot example
- Architecture documentation (`docs/architecture.md`)
- 50 unit tests
