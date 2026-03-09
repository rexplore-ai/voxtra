# Changelog

All notable changes to Voxtra will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
