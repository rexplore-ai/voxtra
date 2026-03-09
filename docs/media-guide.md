# Media Layer — Concepts & Implementation Guide

> A deep dive into Voxtra's media layer: why each concept exists, how audio flows through the system, and the engineering decisions behind codec conversion, framing, and transport.

---

## Why Does Voxtra Need a Media Layer?

Telephony and AI speak **different audio languages**:

| Telephony Side | AI Side |
|---------------|---------|
| μ-law or A-law compressed audio (G.711) | Raw PCM or provider-specific formats |
| 8 kHz sample rate, mono | 16 kHz+ sample rate preferred by some models |
| Small frames (20 ms) delivered over RTP/WebSocket | Streaming or batch audio input |
| Real-time, latency-critical | Processing latency varies |

The media layer **bridges this gap**. It receives compressed telephony audio, converts it to a format AI providers understand, and reverses the process for AI-generated speech going back to the caller.

Without this layer, every AI provider integration would need to implement its own codec conversion, framing, and transport logic — duplicating effort and creating coupling between telephony and AI code.

---

## Audio Fundamentals

### What Is Digital Audio?

Sound is a continuous analog wave. To process it digitally, we **sample** the wave at regular intervals and record each sample's amplitude as a number.

```
Analog sound wave:        Digital samples (PCM):
                          
    ╱╲      ╱╲            Sample 1: 0
   ╱  ╲    ╱  ╲           Sample 2: 12450
  ╱    ╲  ╱    ╲          Sample 3: 24300
 ╱      ╲╱      ╲         Sample 4: 12450
╱                 ╲        Sample 5: 0
                   ╲       Sample 6: -12450
                    ╲╱     Sample 7: -24300
                           Sample 8: -12450
```

Three parameters define digital audio:

- **Sample rate** — How many samples per second (Hz). Telephony uses **8000 Hz** (8 kHz), capturing frequencies up to 4 kHz (the human voice range). Music uses 44100 Hz or 48000 Hz.
- **Bit depth** — How many bits per sample. Voxtra uses **16-bit signed** integers (range −32768 to +32767). More bits = finer amplitude resolution.
- **Channels** — Mono (1) or stereo (2). Telephony is always **mono**.

### Why 8 kHz?

The telephone network was designed for human speech, which contains most of its energy between 300 Hz and 3400 Hz. By the **Nyquist theorem**, you need at least twice the highest frequency to accurately digitize a signal. 3400 Hz × 2 ≈ 7000 Hz, rounded up to **8000 Hz** for a clean sampling rate. This has been the telephony standard since the 1960s.

### Bandwidth Calculation

```
Uncompressed PCM at 8 kHz, 16-bit, mono:
  8000 samples/sec × 16 bits/sample × 1 channel = 128,000 bits/sec = 128 kbps

G.711 μ-law at 8 kHz, 8-bit, mono:
  8000 samples/sec × 8 bits/sample × 1 channel = 64,000 bits/sec = 64 kbps
```

G.711 cuts bandwidth in half compared to raw PCM while preserving voice quality.

---

## Codecs: Why We Convert

### The Problem

AI providers (Deepgram, ElevenLabs, OpenAI) typically work with **PCM** audio — raw, uncompressed samples. But telephony systems transmit **compressed** audio using codecs like G.711 μ-law or A-law to save bandwidth.

Voxtra must convert between these formats at the boundary between telephony and AI.

### G.711 μ-law (Mu-law)

**Used in:** North America, Japan

**How it works:** μ-law uses a **logarithmic companding** curve to compress 16-bit PCM (65536 possible values) into 8-bit values (256 possible values). The curve is designed so that quiet sounds get more resolution than loud sounds — this matches how human hearing works (we're more sensitive to quiet sounds).

```
The μ-law compression formula:

  F(x) = sgn(x) × ln(1 + μ|x|) / ln(1 + μ)

Where μ = 255 (for 8-bit encoding)
```

**Why logarithmic?** Human hearing perceives loudness on a roughly logarithmic scale. A linear encoding would waste bits on loud sounds that don't need fine resolution, while under-representing the quiet sounds that matter most.

**In Voxtra's code** (`src/voxtra/media/audio.py`):
- `_ulaw_to_pcm()` — Expands 8-bit μ-law samples back to 16-bit PCM using the ITU-T G.711 decode table
- `_pcm_to_ulaw()` — Compresses 16-bit PCM samples to 8-bit μ-law using the encode algorithm
- `_linear_to_ulaw()` — The per-sample encode function implementing the G.711 compression with bias (0x84) and clipping (32635)

### G.711 A-law

**Used in:** Europe, Africa, most of the world outside North America

**How it works:** Similar logarithmic companding to μ-law, but with a slightly different curve. A-law provides slightly better quality at lower signal levels, while μ-law performs slightly better at higher signal levels.

**In Voxtra's code:**
- `_alaw_to_pcm()` — Decodes A-law to PCM
- `_pcm_to_alaw()` — Encodes PCM to A-law
- `_alaw_decode_sample()` / `_linear_to_alaw()` — Per-sample conversion

### The Conversion Path

```
Inbound (caller → AI):
  Asterisk sends μ-law audio
    → AudioFrame with codec=ULAW
    → frame.to_pcm_s16le()
    → AudioFrame with codec=PCM_S16LE
    → Passed to STT provider

Outbound (AI → caller):
  TTS generates PCM audio
    → AudioFrame with codec=PCM_S16LE
    → convert_audio(data, from_codec=PCM_S16LE, to_codec=ULAW)
    → Raw μ-law bytes
    → Sent to Asterisk via WebSocket
```

### Why Pure Python?

The codec conversion in Voxtra is implemented in pure Python (no C extensions). This is intentional for the MVP:

- **Zero native dependencies** — No compilation step, works everywhere Python runs
- **Readable** — Contributors can understand and modify the code
- **Sufficient for MVP scale** — The conversion is fast enough for dozens of concurrent calls

For production at scale (hundreds of simultaneous calls), this could be replaced with:
- `audioop` (deprecated but fast) 
- A small C extension
- NumPy-based vectorized operations

---

## AudioFrame: The Universal Audio Container

### Why a Dedicated Data Model?

Every component in the pipeline handles audio differently:
- Media transport sends/receives raw bytes
- STT expects a stream of frames with metadata
- TTS generates frames with specific sample rates
- VAD needs to calculate energy from frame data
- The pipeline needs to track timing and ordering

`AudioFrame` is a **Pydantic model** that wraps raw audio bytes with all the metadata needed for correct processing:

```python
class AudioFrame(BaseModel):
    data: bytes = b""           # Raw audio bytes
    sample_rate: int = 8000     # Samples per second (Hz)
    channels: int = 1           # Always mono for telephony
    codec: AudioCodec = AudioCodec.PCM_S16LE  # Current encoding
    timestamp_ms: float = 0.0   # Position in the audio stream
    duration_ms: float = 20.0   # How much time this frame represents
    sequence: int = 0           # Ordering number
```

### Why 20 ms Frames?

The **20 ms frame duration** is the standard in VoIP telephony:

- **RTP packetization** — Most SIP endpoints send one RTP packet every 20 ms
- **Latency trade-off** — Smaller frames (10 ms) reduce latency but increase packet overhead. Larger frames (40 ms) reduce overhead but add latency. 20 ms is the sweet spot.
- **Processing alignment** — VAD, STT, and other audio processors typically expect 20 ms frames

At 8 kHz, 16-bit PCM, a 20 ms frame contains:
```
8000 samples/sec × 0.020 sec = 160 samples
160 samples × 2 bytes/sample = 320 bytes per frame
```

### Utility Properties

AudioFrame provides computed properties for convenience:

- `n_samples` — Number of audio samples in the frame
- `size_bytes` — Size of the audio data
- `is_silence` — Whether the frame is all zeros (silence)
- `energy` — RMS energy level (used by VAD)
- `to_pcm_s16le()` — Convert the frame's audio to PCM format

---

## SilenceFrame: Generating Silence

`SilenceFrame` is a factory class that creates AudioFrame objects filled with zeros (digital silence). Used for:

- **Hold audio** — Playing silence while a call is on hold (before MOH kicks in)
- **Padding** — Filling gaps in the audio stream caused by jitter or processing delays
- **Testing** — Generating predictable audio for unit tests

```python
silence = SilenceFrame.create(duration_ms=100, sample_rate=8000)
# Creates an AudioFrame with 800 zero samples (100ms at 8kHz)
```

---

## Audio Buffer: Absorbing Jitter

### The Problem

Network audio doesn't arrive in perfect 20 ms intervals. Packets can be delayed, arrive out of order, or come in bursts. If the AI pipeline processes audio as soon as it arrives, it will stutter and skip.

### The Solution

`AudioBuffer` (`src/voxtra/media/buffer.py`) is an async-safe buffer that sits between the media transport and the AI pipeline:

```
Media Transport → push frames → [AudioBuffer] → drain frames → STT Pipeline
                                 ↑
                         Absorbs jitter,
                         enforces ordering,
                         prevents overflow
```

**Key features:**

- **Async-safe** — Uses `asyncio.Event` for signaling between producer and consumer
- **Bounded** — Configurable `max_duration_ms` prevents unbounded memory growth
- **Overflow handling** — When full, evicts oldest frames (better to drop old audio than block)
- **Minimum drain threshold** — Won't drain until enough audio has accumulated, reducing processing overhead
- **Stream interface** — `stream()` yields frames continuously for pipeline consumption

### Why Not Just Use asyncio.Queue?

`asyncio.Queue` provides basic FIFO buffering, but AudioBuffer adds:
- Duration-based capacity (ms, not frame count)
- Overflow eviction policy
- Minimum accumulation threshold
- Total duration tracking
- Silence detection across the buffer

---

## Media Transport: Bridging Audio I/O

### BaseMediaTransport

The abstract interface for all media transports defines four operations:

| Method | Purpose |
|--------|---------|
| `connect(endpoint)` | Open the transport connection |
| `receive_audio()` | Async generator yielding AudioFrames from the caller |
| `send_audio(frame)` | Send an AudioFrame to the caller |
| `disconnect()` | Close the connection |

### Why an Abstraction?

Different telephony backends use different audio transport mechanisms:

| Backend | Transport | Why |
|---------|-----------|-----|
| **Asterisk** | WebSocket (`chan_websocket`) | Asterisk handles RTP internally, exposes audio via WebSocket for external apps |
| **Asterisk** | RTP (direct) | Higher performance but requires manual RTP packet handling |
| **LiveKit** | WebRTC data channels | LiveKit uses WebRTC internally, exposes audio via its SDK |
| **FreeSWITCH** | Event Socket + RTP | FreeSWITCH uses its own event protocol |

By abstracting the transport, the AI pipeline doesn't care how audio arrives — it always works with `AudioFrame` objects from `receive_audio()`.

### WebSocketMediaTransport

The default and recommended transport for the Asterisk backend.

**How it works:**

1. Asterisk creates an **external media channel** pointed at a WebSocket endpoint
2. `WebSocketMediaTransport` connects to that endpoint
3. Asterisk sends raw audio bytes (μ-law) as binary WebSocket messages
4. The transport wraps each message in an `AudioFrame`, converts to PCM, and yields it
5. For outbound audio, the transport converts PCM back to μ-law and sends it

**Why WebSocket over raw RTP?**

| Concern | WebSocket | Raw RTP |
|---------|-----------|---------|
| **Framing** | Automatic — each message = one frame | Manual — must parse RTP headers |
| **Ordering** | TCP guarantees order | UDP — may arrive out of order |
| **NAT** | Works through firewalls | Needs STUN/TURN for NAT traversal |
| **Debugging** | Easy with browser dev tools | Requires Wireshark |
| **Performance** | TCP overhead, ~2ms extra latency | Minimal overhead, lowest latency |
| **Complexity** | Simple | Complex (sequence numbers, SSRC, payload types) |

WebSocket is the right default for development and moderate-scale production. A raw RTP transport can be added for latency-critical deployments.

---

## The Complete Audio Path

### Inbound: Caller Speaks → AI Processes

```
1. Caller speaks into phone
2. Cellular network digitizes voice → SIP/RTP
3. SIP trunk delivers call to Asterisk
4. Asterisk decodes SIP, creates channel
5. Asterisk routes to Stasis app → ARI event
6. Asterisk creates external media channel
7. Audio flows: Asterisk → WebSocket → Voxtra

   [μ-law bytes, 8kHz, 20ms frames]
        │
        ▼
   WebSocketMediaTransport.receive_audio()
        │
        ├─ Wraps bytes in AudioFrame
        ├─ Converts μ-law → PCM (frame.to_pcm_s16le())
        │
        ▼
   [PCM AudioFrame, 8kHz, 16-bit]
        │
        ▼
   VoicePipeline receive loop
        │
        ├─ VAD processes frame (speech/silence detection)
        ├─ Pushes frame to AudioBuffer
        │
        ▼
   VoicePipeline process loop
        │
        ├─ Drains AudioBuffer
        ├─ Streams frames to STT (DeepgramSTT.transcribe_stream())
        │
        ▼
   TranscriptionResult { text: "Hello, I need help", is_final: true }
```

### Outbound: AI Responds → Caller Hears

```
1. LLM generates response text

   "I'd be happy to help. What seems to be the issue?"
        │
        ▼
2. TTS synthesizes audio (ElevenLabsTTS.synthesize())
        │
        ├─ Streaming: yields AudioFrame chunks as generated
        │  (each chunk might be 100-500ms of audio)
        │
        ▼
   [PCM AudioFrame, sample_rate varies by TTS]
        │
        ▼
3. WebSocketMediaTransport.send_audio(frame)
        │
        ├─ Converts PCM → μ-law (convert_audio())
        ├─ Sends binary WebSocket message
        │
        ▼
   [μ-law bytes] → Asterisk → RTP → SIP trunk → caller's phone
```

---

## Design Decisions & Rationale

### Why Pydantic for AudioFrame?

- **Validation** — Ensures sample_rate, channels, codec are valid values
- **Immutability** — Frames are value objects; create new ones rather than mutating
- **Serialization** — Can be serialized to JSON for logging, debugging, or network transport
- **IDE support** — Full autocompletion and type checking

### Why Not Use NumPy?

NumPy would be faster for audio processing, but:
- It's a heavy dependency for a framework that should be lightweight
- The audio processing (codec conversion, energy calculation) is simple enough in pure Python
- Users can add NumPy in their own pipeline stages if needed

### Why Convert at the Transport Boundary?

Audio is converted to PCM at the **earliest possible point** (in `receive_audio()`) and back to the telephony codec at the **latest possible point** (in `send_audio()`). This means the entire internal pipeline works with a single format (PCM S16LE), simplifying every component.

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/voxtra/media/audio.py` | `AudioFrame` model, `SilenceFrame`, codec conversion functions (`convert_audio`, `_ulaw_to_pcm`, `_pcm_to_ulaw`, `_alaw_to_pcm`, `_pcm_to_alaw`) |
| `src/voxtra/media/base.py` | `BaseMediaTransport` abstract class |
| `src/voxtra/media/websocket.py` | `WebSocketMediaTransport` — WebSocket-based audio I/O |
| `src/voxtra/media/buffer.py` | `AudioBuffer` — async jitter buffer |
| `src/voxtra/types.py` | `AudioCodec` enum (`ULAW`, `ALAW`, `PCM_S16LE`, `OPUS`), `MediaTransportType` enum |
