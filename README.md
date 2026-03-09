# Voxtra

**Open voice infrastructure for AI agents.**

Built by [Rexplore Research Labs](https://github.com/rexplore-ai)

---

Voxtra is a Python framework that bridges telephony infrastructure (Asterisk, FreeSWITCH, LiveKit) with AI voice agents (STT, LLM, TTS). It lets developers build AI-powered call centers without needing to understand telecom internals.

## Architecture

```
Cellular Provider (Airtel / TNM / etc.)
        │
   SIP Trunk
        │
     Asterisk (PBX / Call routing)
        │
     Voxtra (Voice AI Bridge)
        │
   ┌────┴─────────────────┐
   │   Voice AI Pipeline  │
   ├── STT (Deepgram)     │
   ├── LLM (OpenAI/Claude)│
   └── TTS (ElevenLabs)   │
   └──────────────────────┘
```

### Layer Design

| Layer | Package | Responsibility |
|-------|---------|---------------|
| **Core** | `voxtra.app`, `voxtra.router`, `voxtra.session` | App lifecycle, routing, call sessions |
| **Telephony** | `voxtra.telephony` | Asterisk ARI, LiveKit, FreeSWITCH adapters |
| **Media** | `voxtra.media` | Audio frames, WebSocket/RTP transport, codecs |
| **AI** | `voxtra.ai` | STT, TTS, LLM, VAD provider abstractions |
| **Pipeline** | `voxtra.core.pipeline` | Real-time STT → LLM → TTS orchestration |

## Quick Start

### Installation

```bash
pip install voxtra
```

With provider extras:

```bash
pip install voxtra[asterisk,deepgram,openai,elevenlabs]
```

### Code-First Usage

```python
from voxtra import VoxtraApp

app = VoxtraApp.from_yaml("voxtra.yaml")

@app.route(extension="1000")
async def support_call(session):
    await session.answer()
    await session.say("Hello, welcome to support. How can I help you?")
    text = await session.listen()
    reply = await session.agent.respond(text)
    await session.say(reply.text)
    await session.hangup()

app.run()
```

### Config-First Usage

Create `voxtra.yaml`:

```yaml
app_name: my-call-center

telephony:
  provider: asterisk
  asterisk:
    base_url: http://localhost:8088
    username: asterisk
    password: secret
    app_name: voxtra

media:
  transport: websocket
  codec: ulaw
  sample_rate: 8000

ai:
  stt:
    provider: deepgram
    api_key: ${DEEPGRAM_API_KEY}
    model: nova-2
  llm:
    provider: openai
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o
    system_prompt: "You are a helpful voice assistant for a call center."
  tts:
    provider: elevenlabs
    api_key: ${ELEVENLABS_API_KEY}
    voice_id: your-voice-id

routes:
  - extension: "1000"
    agent: support_agent
```

Then run:

```bash
voxtra start
```

## Asterisk Integration

Voxtra connects to Asterisk via **ARI (Asterisk REST Interface)**. Add this to your Asterisk dialplan:

```ini
[voxtra-inbound]
exten => _X.,1,Stasis(voxtra)
 same => n,Hangup()
```

## Supported Providers

### Telephony
- **Asterisk** (ARI) — Production ready
- **LiveKit** (SIP) — Planned
- **FreeSWITCH** — Planned

### Speech-to-Text
- **Deepgram** (streaming)
- More coming soon

### LLM / Agents
- **OpenAI** (GPT-4o, streaming)
- LangGraph integration planned

### Text-to-Speech
- **ElevenLabs** (streaming)
- More coming soon

## Project Structure

```
src/voxtra/
├── app.py                  # VoxtraApp — main entry point
├── session.py              # CallSession — per-call handle
├── router.py               # Decorator-based call routing
├── events.py               # Event system
├── config.py               # Pydantic config models
├── middleware.py            # Event middleware
├── exceptions.py           # Custom exceptions
├── types.py                # Shared types
├── core/
│   └── pipeline.py         # STT → LLM → TTS pipeline
├── telephony/
│   ├── base.py             # TelephonyAdapter ABC
│   ├── asterisk/           # Asterisk ARI adapter
│   └── livekit/            # LiveKit adapter (stub)
├── media/
│   ├── audio.py            # AudioFrame, codec conversion
│   ├── base.py             # MediaTransport ABC
│   ├── websocket.py        # WebSocket transport
│   └── buffer.py           # Audio buffering
└── ai/
    ├── stt/                # Speech-to-Text providers
    ├── tts/                # Text-to-Speech providers
    ├── llm/                # LLM / Agent providers
    └── vad/                # Voice Activity Detection
```

## Development

```bash
git clone git@github.com:rexplore-ai/voxtra.git
cd voxtra
pip install -e ".[dev]"
pytest
```

## Roadmap

- [x] Core abstractions (VoxtraApp, Router, CallSession, Events)
- [x] Asterisk ARI adapter
- [x] AI provider interfaces (STT, TTS, LLM, VAD)
- [x] WebSocket media transport
- [x] Voice pipeline (STT → LLM → TTS)
- [ ] End-to-end Asterisk + AI demo
- [ ] LiveKit adapter
- [ ] FreeSWITCH adapter
- [ ] LangGraph agent integration
- [ ] Multi-agent handoff
- [ ] Dashboard / Admin API
- [ ] Conversation analytics

## License

Apache 2.0 — See [LICENSE](LICENSE)

---

**Voxtra** — *The LangGraph of AI Telephony*
Built by Rexplore Research Labs
