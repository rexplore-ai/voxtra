# Contributing to Voxtra

Thank you for your interest in contributing to Voxtra! This project is built and maintained by [Rexplore Research Labs](https://github.com/rexplore-ai), and we welcome contributions from the community.

Voxtra aims to become the standard open-source framework for AI telephony — bridging PBX systems like Asterisk with modern AI voice agents. Every contribution, whether it's a bug fix, a new provider adapter, documentation, or a feature, helps make AI call centers accessible to more developers.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [How to Contribute](#how-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Features](#suggesting-features)
  - [Submitting Code](#submitting-code)
  - [Adding a New AI Provider](#adding-a-new-ai-provider)
  - [Adding a New Telephony Adapter](#adding-a-new-telephony-adapter)
  - [Improving Documentation](#improving-documentation)
- [Code Style and Standards](#code-style-and-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Architecture Overview](#architecture-overview)
- [Community](#community)

---

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally
3. **Create a branch** for your changes
4. **Make your changes** and write tests
5. **Submit a pull request**

## Development Setup

### Prerequisites

- Python 3.11 or higher
- Git

### Clone and Install

```bash
# Clone your fork
git clone git@github.com:YOUR_USERNAME/voxtra.git
cd voxtra

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode with all dev dependencies
pip install -e ".[dev]"

# Verify the install
voxtra info
```

### Install with Provider Extras

If you're working on a specific provider, install its extras:

```bash
# Asterisk adapter
pip install -e ".[asterisk]"

# All providers
pip install -e ".[all,dev]"
```

### Run the Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_router.py -v

# Run with coverage
pytest --cov=voxtra --cov-report=term-missing
```

### Lint and Type Check

```bash
# Lint with ruff
ruff check src/ tests/

# Auto-fix lint issues
ruff check --fix src/ tests/

# Type check with mypy
mypy src/voxtra/
```

---

## Project Structure

```
voxtra/
├── pyproject.toml              # Package metadata, dependencies, tool config
├── README.md                   # Project overview and quick start
├── CONTRIBUTING.md             # This file
├── LICENSE                     # Apache 2.0
├── docs/
│   └── architecture.md         # Detailed architecture documentation
├── examples/
│   └── basic_support_bot/      # Example: AI support bot
│       ├── main.py
│       └── voxtra.yaml
├── src/voxtra/                 # Main package
│   ├── __init__.py             # Package exports
│   ├── app.py                  # VoxtraApp — main entry point
│   ├── session.py              # CallSession — per-call developer handle
│   ├── router.py               # Decorator-based call routing
│   ├── events.py               # Event types and models
│   ├── config.py               # Pydantic configuration models
│   ├── middleware.py            # Event middleware system
│   ├── exceptions.py           # Custom exception hierarchy
│   ├── types.py                # Shared enums and type aliases
│   ├── cli.py                  # CLI entry point (voxtra command)
│   ├── core/
│   │   └── pipeline.py         # VoicePipeline (STT → LLM → TTS)
│   ├── telephony/
│   │   ├── base.py             # BaseTelephonyAdapter (ABC)
│   │   ├── asterisk/
│   │   │   ├── adapter.py      # Asterisk ARI adapter
│   │   │   └── __init__.py
│   │   └── livekit/
│   │       ├── adapter.py      # LiveKit adapter (stub)
│   │       └── __init__.py
│   ├── media/
│   │   ├── audio.py            # AudioFrame, codec conversion
│   │   ├── base.py             # BaseMediaTransport (ABC)
│   │   ├── websocket.py        # WebSocket media transport
│   │   └── buffer.py           # Async audio buffer
│   └── ai/
│       ├── stt/
│       │   ├── base.py         # BaseSTT (ABC)
│       │   └── deepgram.py     # Deepgram streaming STT
│       ├── tts/
│       │   ├── base.py         # BaseTTS (ABC)
│       │   └── elevenlabs.py   # ElevenLabs streaming TTS
│       ├── llm/
│       │   ├── base.py         # BaseAgent (ABC)
│       │   └── openai.py       # OpenAI chat agent
│       └── vad/
│           └── base.py         # BaseVAD (ABC) + EnergyVAD
└── tests/
    ├── test_config.py          # Configuration tests
    ├── test_router.py          # Routing tests
    ├── test_events.py          # Event system tests
    ├── test_session.py         # CallSession tests
    └── test_audio.py           # Audio frame and codec tests
```

---

## How to Contribute

### Reporting Bugs

Open a [GitHub Issue](https://github.com/rexplore-ai/voxtra/issues) with:

- **Title**: Short description of the bug
- **Environment**: Python version, OS, Voxtra version (`voxtra info`)
- **Steps to reproduce**: Minimal code or configuration to trigger the bug
- **Expected vs actual behavior**
- **Logs/tracebacks** if available

### Suggesting Features

Open an issue with the `enhancement` label. Include:

- **Use case**: What problem does this solve?
- **Proposed API**: How should it look to developers?
- **Alternatives considered**: What other approaches exist?

### Submitting Code

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. Make your changes following our [code style](#code-style-and-standards)

3. Write or update tests for your changes

4. Ensure all tests pass:
   ```bash
   pytest -v
   ```

5. Commit with a descriptive message:
   ```bash
   git commit -m "feat: add Cartesia TTS provider"
   ```

6. Push and open a pull request against `main`

### Adding a New AI Provider

This is one of the most valuable contributions. Voxtra uses abstract base classes so new providers are easy to add.

#### Adding an STT Provider

1. Create `src/voxtra/ai/stt/your_provider.py`
2. Subclass `BaseSTT` from `voxtra.ai.stt.base`
3. Implement the required methods:

```python
from voxtra.ai.stt.base import BaseSTT, TranscriptionResult
from voxtra.config import STTConfig
from voxtra.media.audio import AudioFrame

class YourSTT(BaseSTT):
    def __init__(self, config: STTConfig) -> None:
        super().__init__(config)

    async def connect(self) -> None:
        # Initialize your SDK client
        ...

    async def transcribe_stream(self, audio_stream):
        # Stream audio frames → yield TranscriptionResult
        async for frame in audio_stream:
            result = ...  # Your transcription logic
            yield TranscriptionResult(text=result, is_final=True)

    async def transcribe(self, audio_data: bytes) -> TranscriptionResult:
        # Batch transcription
        ...

    async def disconnect(self) -> None:
        # Clean up
        ...
```

4. Register it in `VoxtraApp._create_stt_provider()` in `src/voxtra/app.py`
5. Add the SDK to `pyproject.toml` optional dependencies
6. Write tests in `tests/test_stt_your_provider.py`

#### Adding a TTS Provider

Same pattern — subclass `BaseTTS` from `voxtra.ai.tts.base`:

```python
from voxtra.ai.tts.base import BaseTTS
from voxtra.media.audio import AudioFrame

class YourTTS(BaseTTS):
    async def connect(self) -> None: ...
    async def synthesize(self, text: str):  # -> AsyncIterator[AudioFrame]
        # Yield audio frames as they're generated
        yield AudioFrame(data=audio_chunk, sample_rate=8000)
    async def synthesize_full(self, text: str) -> bytes: ...
    async def disconnect(self) -> None: ...
```

#### Adding an LLM/Agent Provider

Subclass `BaseAgent` from `voxtra.ai.llm.base`:

```python
from voxtra.ai.llm.base import BaseAgent, AgentResponse

class YourAgent(BaseAgent):
    async def connect(self) -> None: ...
    async def respond(self, text, *, history=None, system_prompt=None):
        return AgentResponse(text="response")
    async def respond_stream(self, text, *, history=None, system_prompt=None):
        yield "partial response"
    async def disconnect(self) -> None: ...
```

### Adding a New Telephony Adapter

Subclass `BaseTelephonyAdapter` from `voxtra.telephony.base`:

1. Create a new directory: `src/voxtra/telephony/your_pbx/`
2. Implement the adapter:

```python
from voxtra.telephony.base import BaseTelephonyAdapter, EventCallback

class YourPBXAdapter(BaseTelephonyAdapter):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def listen(self, callback: EventCallback) -> None: ...
    async def answer_call(self, channel_id: str) -> None: ...
    async def hangup_call(self, channel_id: str) -> None: ...
    async def transfer_call(self, channel_id: str, target: str) -> None: ...
    async def hold_call(self, channel_id: str) -> None: ...
    async def send_dtmf(self, channel_id: str, digits: str) -> None: ...
    async def create_media_bridge(self, channel_id: str) -> str: ...
    async def play_audio(self, channel_id: str, audio_uri: str) -> None: ...
```

3. Register it in `VoxtraApp._create_telephony_adapter()` in `src/voxtra/app.py`

### Improving Documentation

Documentation lives in:

- `README.md` — Quick start and overview
- `CONTRIBUTING.md` — This file
- `docs/architecture.md` — Detailed architecture
- Docstrings in every module, class, and method

We use Google-style docstrings. Every public class and method should be documented.

---

## Code Style and Standards

### General Rules

- **Python 3.11+** — Use modern syntax (`X | Y` unions, `match` statements where appropriate)
- **Async-first** — All I/O operations must be async
- **Type hints** — All function signatures must have type annotations
- **Docstrings** — All public modules, classes, and methods must have docstrings
- **No hardcoded secrets** — API keys come from config or environment variables

### Formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

- Line length: **100 characters**
- Import sorting: isort-compatible
- Target: Python 3.11

```bash
# Check
ruff check src/ tests/

# Fix
ruff check --fix src/ tests/
```

### Naming Conventions

| Item | Convention | Example |
|------|-----------|---------|
| Modules | `snake_case` | `asterisk_adapter.py` |
| Classes | `PascalCase` | `AsteriskARIAdapter` |
| Functions | `snake_case` | `answer_call` |
| Constants | `UPPER_SNAKE` | `MAX_BUFFER_SIZE` |
| Private | `_leading_underscore` | `_translate_event` |
| Abstract base classes | `Base` prefix | `BaseSTT`, `BaseTTS` |

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add Cartesia TTS provider
fix: handle ARI reconnection on timeout
docs: add LiveKit integration guide
test: add codec roundtrip tests
refactor: extract audio processing into separate module
```

---

## Testing

### Test Structure

Tests mirror the source structure:

| Source | Tests |
|--------|-------|
| `src/voxtra/config.py` | `tests/test_config.py` |
| `src/voxtra/router.py` | `tests/test_router.py` |
| `src/voxtra/events.py` | `tests/test_events.py` |
| `src/voxtra/session.py` | `tests/test_session.py` |
| `src/voxtra/media/audio.py` | `tests/test_audio.py` |

### Writing Tests

- Use `pytest` with `pytest-asyncio` for async tests
- Mark async tests with `@pytest.mark.asyncio` (or rely on `asyncio_mode=auto`)
- Test both happy paths and error cases
- Mock external services (Deepgram, OpenAI, etc.) — don't call real APIs in tests

```python
import pytest
from voxtra.router import Router

class TestMyFeature:
    @pytest.mark.asyncio
    async def test_something(self) -> None:
        router = Router()
        # ... test logic
        assert result == expected
```

### Running Tests

```bash
# All tests
pytest

# Verbose
pytest -v

# Specific file
pytest tests/test_router.py

# With coverage
pytest --cov=voxtra --cov-report=html
```

---

## Pull Request Process

1. **Branch** from `main` with a descriptive name (`feat/`, `fix/`, `docs/`)
2. **Keep PRs focused** — one feature or fix per PR
3. **All tests must pass** — `pytest` exits with 0
4. **Lint clean** — `ruff check` exits with 0
5. **Write a clear PR description** explaining:
   - What changed
   - Why it changed
   - How to test it
6. **Link related issues** if applicable

### PR Checklist

- [ ] Tests added/updated
- [ ] All tests pass (`pytest -v`)
- [ ] Lint passes (`ruff check src/ tests/`)
- [ ] Docstrings added for new public APIs
- [ ] `CONTRIBUTING.md` or `docs/` updated if needed
- [ ] No hardcoded API keys or secrets

---

## Architecture Overview

For a detailed deep-dive into Voxtra's architecture, see **[docs/architecture.md](docs/architecture.md)**.

Quick summary of the layers:

```
┌─────────────────────────────────────────────┐
│  Developer Code                             │
│  @app.route(extension="1000")               │
│  async def handler(session): ...            │
├─────────────────────────────────────────────┤
│  voxtra.app / voxtra.router                 │
│  VoxtraApp, Router, Middleware              │
├─────────────────────────────────────────────┤
│  voxtra.session                             │
│  CallSession (say, listen, transfer, etc.)  │
├─────────────────────────────────────────────┤
│  voxtra.core.pipeline                       │
│  VoicePipeline (STT → LLM → TTS loop)      │
├─────────────────────────────────────────────┤
│  voxtra.ai                                  │
│  BaseSTT / BaseTTS / BaseAgent / BaseVAD    │
├─────────────────────────────────────────────┤
│  voxtra.media                               │
│  AudioFrame, WebSocket/RTP transport        │
├─────────────────────────────────────────────┤
│  voxtra.telephony                           │
│  Asterisk ARI / LiveKit / FreeSWITCH        │
├─────────────────────────────────────────────┤
│  Infrastructure                             │
│  Asterisk ← SIP Trunk ← Cellular Provider  │
└─────────────────────────────────────────────┘
```

---

## Areas Where We Need Help

These are high-impact areas where contributions are especially welcome:

### Providers
- **Cartesia TTS** — Low-latency TTS ideal for telephony
- **Whisper STT** — Local/self-hosted speech recognition
- **Anthropic Claude** — Claude agent support
- **Google Cloud STT/TTS** — Google provider adapters
- **Azure Speech** — Microsoft Cognitive Services

### Telephony
- **LiveKit adapter** — Full implementation of the LiveKit SIP bridge
- **FreeSWITCH adapter** — ESL-based adapter
- **Twilio adapter** — For cloud-hosted telephony

### Features
- **LangGraph integration** — Use LangGraph agents as the LLM layer
- **Multi-agent handoff** — Transfer between AI agents
- **Call recording** — Record and store call audio
- **Conversation analytics** — Post-call analysis and metrics
- **DTMF menu builder** — IVR-style menu system
- **Outbound dialer** — Campaign-based outbound calling

### Infrastructure
- **Docker Compose** — One-command dev environment (Asterisk + Voxtra)
- **CI/CD** — GitHub Actions for testing and publishing
- **Benchmarks** — Latency measurement tooling

---

## Community

- **GitHub Issues**: Bug reports and feature requests
- **GitHub Discussions**: Questions and ideas
- **Pull Requests**: Code contributions

---

## License

By contributing to Voxtra, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).

---

**Voxtra** — *The LangGraph of AI Telephony*
Built by Rexplore Research Labs
