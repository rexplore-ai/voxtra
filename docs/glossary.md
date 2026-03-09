# Voxtra Glossary

> Definitions, abbreviations, and terminology used throughout the Voxtra codebase and documentation.

---

## Telephony & Networking

| Term | Full Form | Definition |
|------|-----------|------------|
| **SIP** | Session Initiation Protocol | The standard signaling protocol used to set up, manage, and tear down voice and video calls over IP networks. SIP handles the "control plane" — it negotiates who is calling whom, what codecs to use, and when to hang up — but does **not** carry the actual audio. |
| **RTP** | Real-time Transport Protocol | The protocol that carries the actual audio (and video) payload during a call. RTP packets contain audio frames, sequence numbers, timestamps, and payload type identifiers. It works alongside SIP, which sets up the session that RTP then streams. |
| **SRTP** | Secure Real-time Transport Protocol | The encrypted variant of RTP. Adds confidentiality, message authentication, and replay protection to audio streams. Required for secure VoIP deployments. |
| **PBX** | Private Branch Exchange | A private telephone system within an organization that switches calls between internal users and connects them to the public telephone network. Asterisk and FreeSWITCH are software PBX systems. |
| **PSTN** | Public Switched Telephone Network | The global network of circuit-switched telephone infrastructure. When someone dials a regular phone number, the call goes through the PSTN. SIP trunks bridge VoIP systems to the PSTN. |
| **VoIP** | Voice over Internet Protocol | The technology for delivering voice communications over IP networks (the internet) instead of traditional circuit-switched telephone lines. |
| **SIP Trunk** | SIP Trunk | A virtual connection between your PBX and a telephony service provider (e.g., Airtel, TNM, Twilio). It replaces physical phone lines, allowing your PBX to make and receive calls over the internet via SIP. |
| **DTMF** | Dual-Tone Multi-Frequency | The tones generated when a user presses a key on a telephone keypad. Each key produces a unique combination of two frequencies. Used for IVR navigation (e.g., "Press 1 for support"). In Voxtra, DTMF events are captured by the telephony adapter and emitted as `DTMFEvent`. |
| **IVR** | Interactive Voice Response | An automated telephony system that interacts with callers using voice prompts and DTMF input. Traditional IVR uses rigid menu trees; Voxtra replaces this with conversational AI. |
| **WebRTC** | Web Real-Time Communication | A set of browser APIs and protocols for peer-to-peer audio, video, and data streaming without plugins. LiveKit builds on WebRTC. |
| **NAT** | Network Address Translation | A technique that maps private IP addresses to a public IP address. Causes complications for SIP/RTP because the audio path needs direct connectivity. Solutions include STUN, TURN, and ICE. |

---

## Asterisk & ARI

| Term | Full Form | Definition |
|------|-----------|------------|
| **Asterisk** | — | An open-source software PBX written in C. It handles SIP signaling, media processing, call routing via dialplans, and provides multiple control interfaces (ARI, AMI, AGI). Voxtra uses Asterisk as its primary telephony backend. |
| **ARI** | Asterisk REST Interface | A modern HTTP + WebSocket API for controlling Asterisk programmatically. ARI gives external applications full control over channels, bridges, and media — which is exactly what Voxtra needs to route call audio through AI pipelines. |
| **AMI** | Asterisk Manager Interface | An older TCP-based management interface for Asterisk. Designed for monitoring and administrative tasks (e.g., originating calls, checking queue status). Less suitable for real-time call control than ARI. |
| **AGI** | Asterisk Gateway Interface | A synchronous scripting interface for Asterisk dialplans. Each AGI call blocks a thread, making it unsuitable for the async, streaming nature of AI voice processing. |
| **Stasis** | — | The ARI application model in Asterisk. When a call enters a Stasis application (via `Stasis(app_name)` in the dialplan), Asterisk hands full control to the external application connected via ARI. The external app receives events and controls the call via REST. |
| **Channel** | — | An Asterisk abstraction representing one endpoint of a call. A SIP phone calling your PBX creates a channel. A two-party call has two channels bridged together. Channels have IDs used for call control (answer, hangup, transfer). |
| **Bridge** | — | An Asterisk construct that mixes audio from multiple channels together. A simple two-party call uses a bridge to connect the caller and callee channels. Voxtra creates bridges with an **external media** channel to route audio through the AI pipeline. |
| **External Media** | — | An Asterisk feature that creates a channel connected to an external audio endpoint (typically via UDP/RTP or WebSocket). Voxtra uses this to stream call audio to/from the AI pipeline. |
| **Dialplan** | — | Asterisk's call routing configuration. Written in `extensions.conf` or `pjsip.conf`, it defines what happens when calls arrive at specific extensions. Voxtra requires a dialplan rule that routes calls into a Stasis application. |
| **PJSIP** | — | The modern SIP channel driver for Asterisk (replacing the older `chan_sip`). Handles SIP registration, authentication, codec negotiation, and NAT traversal. |
| **MOH** | Music on Hold | Audio played to callers while they are on hold. Asterisk provides built-in MOH classes. Voxtra uses MOH via `hold_call()`. |

---

## Audio & Codecs

| Term | Full Form | Definition |
|------|-----------|------------|
| **PCM** | Pulse-Code Modulation | The standard method for digitally representing analog audio. Records amplitude values at regular intervals (samples). PCM is uncompressed — it's the raw digital representation of sound. |
| **PCM S16LE** | PCM Signed 16-bit Little-Endian | The specific PCM format Voxtra uses internally. Each audio sample is a signed 16-bit integer (range −32768 to +32767) stored in little-endian byte order. This is the format AI providers (STT, TTS) typically work with. |
| **μ-law (G.711μ)** | Mu-law / G.711 Mu-law | A companding algorithm defined in ITU-T G.711 that compresses 16-bit PCM samples into 8 bits. Used in North American and Japanese telephone networks. Reduces bandwidth by 50% while preserving voice quality. Voxtra converts between μ-law and PCM when bridging telephony audio to AI providers. |
| **A-law (G.711A)** | A-law / G.711 A-law | The European/international counterpart to μ-law. Also compresses 16-bit PCM to 8 bits, but uses a slightly different companding curve. Used in European and most international telephone networks. |
| **G.711** | ITU-T G.711 | The ITU standard for audio companding in telephony. Defines both μ-law and A-law. Operates at 8 kHz sample rate, producing 64 kbps audio. The most universally supported telephony codec. |
| **Opus** | — | A modern, open audio codec designed for interactive speech and music. Supports variable bitrate, multiple sample rates, and very low latency. Used by WebRTC and LiveKit. |
| **Codec** | Coder-Decoder | An algorithm that encodes and decodes audio data. In telephony, codecs compress audio for efficient transmission. Common telephony codecs include G.711 (μ-law/A-law), G.729, and Opus. |
| **Companding** | Compressing-Expanding | The technique used by μ-law and A-law codecs. Audio is compressed (companded) at the sender using a logarithmic curve, and expanded back at the receiver. This preserves quality for quiet sounds while using fewer bits. |
| **Sample Rate** | — | The number of audio samples captured per second, measured in Hertz (Hz). Telephony standard is **8000 Hz** (8 kHz), meaning 8000 amplitude measurements per second. Higher sample rates capture more audio detail but require more bandwidth. |
| **Frame** | — | A discrete chunk of audio data representing a fixed time interval. In Voxtra, the default frame duration is **20 ms**. At 8 kHz with 16-bit PCM, a 20 ms frame contains 160 samples = 320 bytes. Frames are the unit of audio processing throughout the pipeline. |
| **Mono / Stereo** | — | The number of audio channels. Telephony audio is always **mono** (1 channel). Stereo (2 channels) is used for music but not for phone calls. |
| **RMS** | Root Mean Square | A mathematical measure of signal amplitude (energy). Voxtra's `EnergyVAD` calculates the RMS energy of each audio frame to determine if someone is speaking. Higher RMS = louder audio = likely speech. |
| **Jitter** | — | Variation in the arrival time of network packets. Audio frames should arrive at regular intervals (every 20 ms), but network conditions cause uneven delivery. The `AudioBuffer` in Voxtra absorbs jitter by buffering frames before processing. |

---

## AI & Voice Processing

| Term | Full Form | Definition |
|------|-----------|------------|
| **STT** | Speech-to-Text | The process of converting spoken audio into written text. Also called ASR (Automatic Speech Recognition). In Voxtra, STT providers (e.g., Deepgram) receive audio frames and output `TranscriptionResult` objects containing the recognized text. |
| **TTS** | Text-to-Speech | The process of converting written text into spoken audio. Also called speech synthesis. In Voxtra, TTS providers (e.g., ElevenLabs) receive text and output `AudioFrame` streams that are played back to the caller. |
| **LLM** | Large Language Model | An AI model trained on vast text corpora to understand and generate human language. In Voxtra, LLMs (e.g., GPT-4o) serve as the "brain" of the voice agent — they receive transcribed caller speech and generate intelligent responses. |
| **VAD** | Voice Activity Detection | An algorithm that determines whether an audio signal contains human speech or silence. Critical for telephony AI because it enables turn detection (knowing when the caller stopped talking), barge-in detection (caller interrupting the AI), and silence timeout handling. |
| **ASR** | Automatic Speech Recognition | Synonym for STT. The technology that converts spoken language into text. |
| **NLU** | Natural Language Understanding | The AI capability to comprehend the meaning and intent behind text. LLMs provide NLU as part of their language understanding. |
| **Barge-in** | — | When a caller starts speaking while the AI agent is still talking. Voxtra detects barge-in via VAD and immediately stops TTS playback, allowing the caller to take the conversational turn. This creates a natural, non-robotic interaction. |
| **Turn Detection** | — | Determining when one party in a conversation has finished speaking so the other can respond. In Voxtra, VAD + silence threshold drives turn detection — when the caller stops speaking for a configurable duration, their turn is considered complete. |
| **Interim Results** | — | Partial transcriptions returned by STT providers before the speaker has finished an utterance. Useful for early intent detection and reducing perceived latency. Marked with `is_final=False` in `TranscriptionResult`. |
| **Streaming Synthesis** | — | Generating TTS audio incrementally — yielding audio chunks as they are produced rather than waiting for the entire utterance. Reduces time-to-first-audio, which is critical for conversational latency. |
| **Time-to-First-Byte (TTFB)** | — | The latency between sending a request (e.g., text to TTS) and receiving the first byte of audio response. For voice AI, TTFB should be < 300 ms to feel natural. |

---

## Voxtra Framework

| Term | Definition |
|------|------------|
| **VoxtraApp** | The main application class. Analogous to a Flask/FastAPI `app`. Wires together all components and manages the lifecycle. |
| **CallSession** | A per-call object that provides the developer API for interacting with an active call (`say()`, `listen()`, `hangup()`, etc.). |
| **Router** | Maps incoming calls to handler functions based on extension, phone number, or dynamic rules. |
| **VoicePipeline** | The real-time engine that orchestrates the STT → LLM → TTS loop with concurrent receive and process loops. |
| **AudioFrame** | Pydantic model representing a single chunk of audio data with metadata (sample rate, codec, timestamp, duration). The universal audio container in Voxtra. |
| **AudioBuffer** | Async-safe buffer that absorbs jitter and accumulates audio frames for batch processing. |
| **BaseMiddleware** | Abstract class for event middleware. Intercepts events before they reach handlers, enabling logging, metrics, error handling, etc. |
| **Provider Registry** | A global registry (`voxtra.registry.registry`) that maps provider name strings to implementation classes. Enables plugin architecture — third-party providers can register without modifying core code. |
| **VoxtraEvent** | Base class for all internal events. Carries event type, session ID, timestamp, and arbitrary data payload. |
| **EventCallback** | Type alias for the async function that receives events from telephony adapters: `async (VoxtraEvent) -> None`. |

---

## Protocols & Standards

| Term | Full Form | Definition |
|------|-----------|------------|
| **ITU-T** | International Telecommunication Union – Telecommunication Standardization Sector | The international body that defines telephony standards like G.711 (μ-law/A-law codecs). |
| **RFC 3261** | — | The core SIP specification. Defines how SIP messages (INVITE, ACK, BYE, etc.) establish and manage voice sessions. |
| **RFC 3550** | — | The RTP specification. Defines packet format, sequence numbering, and timing for real-time media delivery. |
| **WebSocket (RFC 6455)** | — | A protocol providing full-duplex communication over a single TCP connection. Voxtra uses WebSocket for both ARI event streaming and media audio transport. |

---

## Common Abbreviations Quick Reference

| Abbreviation | Meaning |
|-------------|---------|
| ARI | Asterisk REST Interface |
| AMI | Asterisk Manager Interface |
| AGI | Asterisk Gateway Interface |
| ASR | Automatic Speech Recognition |
| DTMF | Dual-Tone Multi-Frequency |
| IVR | Interactive Voice Response |
| LLM | Large Language Model |
| MOH | Music on Hold |
| NAT | Network Address Translation |
| NLU | Natural Language Understanding |
| PBX | Private Branch Exchange |
| PCM | Pulse-Code Modulation |
| PSTN | Public Switched Telephone Network |
| RMS | Root Mean Square |
| RTP | Real-time Transport Protocol |
| SIP | Session Initiation Protocol |
| SRTP | Secure Real-time Transport Protocol |
| STT | Speech-to-Text |
| TTFB | Time-to-First-Byte |
| TTS | Text-to-Speech |
| VAD | Voice Activity Detection |
| VoIP | Voice over Internet Protocol |
| WebRTC | Web Real-Time Communication |
