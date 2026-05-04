# Changelog

All notable changes to Voxtra will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
