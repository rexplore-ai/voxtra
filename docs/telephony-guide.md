# Telephony Layer — Concepts & Implementation Guide

> A deep dive into Voxtra's telephony layer: how phone calls work, why Asterisk ARI was chosen, what every concept means, and how calls flow from cellular networks into AI pipelines.

---

## Why Does Voxtra Need a Telephony Layer?

Voxtra's core purpose is to connect **phone calls** to **AI agents**. But phone calls don't just magically appear as audio streams — they go through a complex chain of infrastructure:

```
Caller's phone
    → Cellular tower (Airtel, TNM, etc.)
    → Cellular core network
    → SIP trunk (VoIP gateway)
    → Your PBX (Asterisk)
    → Voxtra
```

The telephony layer handles the last hop: connecting to the PBX, receiving call events, controlling calls (answer, hangup, transfer), and setting up audio bridges for media streaming.

---

## How Phone Calls Work (From Scratch)

### The Signaling / Media Split

Every phone call has two distinct planes:

1. **Signaling plane (SIP)** — The "control" messages: "I want to call this number", "the phone is ringing", "call answered", "call ended". SIP messages set up, modify, and tear down calls. They do **not** carry audio.

2. **Media plane (RTP)** — The actual audio stream. Once SIP establishes a call, RTP packets carry the voice data between endpoints. RTP uses UDP for low latency (dropped packets are better than delayed packets in real-time audio).

```
Signaling (SIP):
  Caller                    PBX (Asterisk)
    │                           │
    │── INVITE (I want to call) ─→│
    │←── 100 Trying ─────────────│
    │←── 180 Ringing ────────────│
    │←── 200 OK (answered) ──────│
    │── ACK ─────────────────────→│
    │                           │
    │     ... call in progress ...
    │                           │
    │── BYE (hang up) ──────────→│
    │←── 200 OK ─────────────────│

Media (RTP):
  Caller ←──── UDP audio packets ────→ PBX
  (bidirectional, ~50 packets/second at 20ms framing)
```

### SIP Trunks

A **SIP trunk** is a virtual connection between your PBX and a telephony service provider. It replaces physical phone lines:

- **Inbound:** The provider routes incoming calls to your PBX via SIP
- **Outbound:** Your PBX sends outgoing calls to the provider via SIP
- **Registration:** Your PBX registers with the provider so they know where to send calls

In Voxtra's config, SIP trunks are defined in `TelephonyConfig.sip_trunks`:

```yaml
telephony:
  sip_trunks:
    - name: airtel-malawi
      host: sip.airtel.mw
      port: 5060
      username: your-account
      password: your-password
      transport: udp
      codec: ulaw
```

The PBX (Asterisk) handles SIP trunk management — Voxtra does not interact with SIP trunks directly.

---

## Asterisk: The PBX

### What Is Asterisk?

Asterisk is an open-source software PBX (Private Branch Exchange) written in C. It runs on Linux and handles:

- **SIP registration and authentication** — Manages connections to SIP trunks and SIP phones
- **Call routing** — Routes calls based on dialed numbers, caller ID, time of day, etc.
- **Media processing** — Transcodes audio between codecs, mixes audio in conferences
- **Voicemail, IVR, queues** — Traditional PBX features
- **Programmable interfaces** — ARI, AMI, and AGI for external application control

### Why Asterisk for Voxtra?

| Reason | Explanation |
|--------|-------------|
| **Open source** | Free, no licensing costs, full source access |
| **Ubiquitous** | Most deployed PBX software worldwide |
| **ARI** | Modern REST + WebSocket API for full programmatic control |
| **External Media** | Native support for routing call audio to external applications |
| **Codec support** | Handles G.711, G.722, Opus, and dozens of other codecs |
| **SIP trunk support** | Connects to any SIP provider (Airtel, TNM, Twilio, etc.) |
| **Battle-tested** | 20+ years in production, handles millions of calls daily |

---

## Asterisk REST Interface (ARI)

### What Is ARI?

ARI is Asterisk's modern programmable interface, designed for building custom communications applications. It provides:

1. **REST API (HTTP)** — Send commands to Asterisk (answer calls, create bridges, play audio)
2. **WebSocket** — Receive real-time events from Asterisk (new call, DTMF pressed, call ended)

This is the interface Voxtra's `AsteriskARIAdapter` uses.

### Why ARI (Not AMI or AGI)?

Asterisk has three control interfaces. Here's why ARI is the right choice:

| Interface | Model | Suitable for Voxtra? | Why? |
|-----------|-------|---------------------|------|
| **ARI** | REST + WebSocket, async | **Yes** | Non-blocking, full call control, media bridging, modern API |
| **AMI** | TCP socket, async | No | Designed for monitoring/management, not real-time call control |
| **AGI** | Stdin/stdout, synchronous | No | Blocks a thread per call, cannot handle streaming audio, no WebSocket |

ARI's event-driven WebSocket model maps perfectly to Voxtra's async architecture.

### ARI Architecture

```
┌──────────────────────────────────────────────────────┐
│                   Asterisk PBX                       │
│                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐   │
│  │ SIP Core │    │ Channels │    │   Bridges     │   │
│  │(PJSIP)   │───→│          │───→│(mixing audio) │   │
│  └──────────┘    └──────────┘    └──────────────┘   │
│                       │                │             │
│                       ▼                ▼             │
│               ┌───────────────────────────┐          │
│               │     ARI (Stasis)          │          │
│               │  REST API + WebSocket     │          │
│               └───────────┬───────────────┘          │
│                           │                          │
└───────────────────────────┼──────────────────────────┘
                            │
                    HTTP + WebSocket
                            │
                            ▼
                ┌───────────────────────┐
                │  Voxtra Application   │
                │  AsteriskARIAdapter   │
                └───────────────────────┘
```

### Stasis: The Application Model

When a call enters Asterisk, the **dialplan** determines what happens. For Voxtra, the dialplan routes calls into a **Stasis application**:

```ini
; In Asterisk's extensions.conf or pjsip.conf:
[voxtra-inbound]
exten => _X.,1,Stasis(voxtra)
 same => n,Hangup()
```

What `Stasis(voxtra)` does:

1. Asterisk **suspends normal dialplan processing** for this call
2. Asterisk emits a `StasisStart` event on the ARI WebSocket
3. The external application (Voxtra) now has **full control** over the call
4. Voxtra decides what to do: answer, play audio, bridge to another channel, hang up
5. When the call ends (or Voxtra releases it), Asterisk emits `StasisEnd`

This is fundamentally different from traditional IVR, where Asterisk runs a fixed script. With Stasis, the external application drives every decision in real time.

### ARI Events

Events flow from Asterisk to Voxtra via the ARI WebSocket. Voxtra's `AsteriskARIAdapter` translates them into `VoxtraEvent` objects:

| ARI Event | When It Fires | Voxtra Translation |
|-----------|--------------|-------------------|
| `StasisStart` | A new call enters the Stasis app | `CallStartedEvent` — Contains caller ID, callee (dialed extension), direction. Triggers session creation and handler dispatch. |
| `StasisEnd` | A call leaves the Stasis app | `CallEndedEvent` — Session cleanup, resources released. |
| `ChannelDtmfReceived` | Caller presses a phone key | `DTMFEvent` — Contains the digit (0-9, *, #). Enables touch-tone navigation in AI agents. |
| `ChannelHangupRequest` | Remote end requests hangup | `CallEndedEvent` — Caller hung up. Triggers graceful session teardown. |
| `ChannelDestroyed` | Channel is fully destroyed | `CallEndedEvent` — Final cleanup signal. |

### ARI REST Operations

Voxtra sends commands to Asterisk via HTTP:

| Operation | HTTP Method | ARI Endpoint | Purpose |
|-----------|------------|-------------|---------|
| **Answer call** | POST | `/ari/channels/{id}/answer` | Pick up a ringing call |
| **Hang up** | DELETE | `/ari/channels/{id}` | End a call |
| **Transfer** | POST | `/ari/channels/{id}/redirect` | Move call to another extension |
| **Hold** | POST | `/ari/channels/{id}/moh` | Play music on hold |
| **Send DTMF** | POST | `/ari/channels/{id}/dtmf` | Send touch-tone digits |
| **Play audio** | POST | `/ari/channels/{id}/play` | Play a sound file or URI |
| **Create bridge** | POST | `/ari/bridges` | Create an audio mixing bridge |
| **Add to bridge** | POST | `/ari/bridges/{id}/addChannel` | Connect channels in a bridge |
| **External media** | POST | `/ari/channels/externalMedia` | Create a channel connected to an external audio endpoint |

---

## Channels and Bridges

### What Is a Channel?

A **channel** in Asterisk represents one endpoint of a communication path. When a SIP phone calls your PBX, Asterisk creates a channel for that call leg.

Think of a channel as a "pipe" — audio flows in and out of it. Key properties:

- **Channel ID** — Unique identifier (e.g., `PJSIP/alice-00000001`)
- **State** — Ringing, Up (answered), Down (hung up)
- **Caller ID** — Who is calling
- **Connected line** — Who they're connected to
- **Codec** — What audio format is being used

### What Is a Bridge?

A **bridge** connects two or more channels so they can hear each other. Without a bridge, channels exist in isolation — no audio flows between them.

Types of bridges:

| Bridge Type | Purpose |
|-------------|---------|
| **Mixing** | Mixes audio from all channels together (like a conference call). This is what Voxtra uses. |
| **Holding** | Plays music on hold to channels. |
| **DTMF** | A hybrid that handles DTMF-based features. |

### External Media: The Audio Bridge to AI

The critical piece that enables Voxtra's AI pipeline is **External Media**. This Asterisk feature creates a channel that connects to an external audio endpoint instead of a SIP phone:

```
Normal call:
  [SIP Phone A] ←→ [Bridge] ←→ [SIP Phone B]

Voxtra call:
  [SIP Phone (caller)] ←→ [Bridge] ←→ [External Media Channel]
                                              │
                                        WebSocket / RTP
                                              │
                                              ▼
                                     [Voxtra AI Pipeline]
```

When `AsteriskARIAdapter.create_media_bridge()` is called, it:

1. Creates a **mixing bridge** — This will mix the audio from the caller and the AI
2. Creates an **external media channel** — Points to Voxtra's media transport endpoint (e.g., `localhost:8089`)
3. Adds **both channels** to the bridge — The caller's channel and the external media channel

Now audio flows bidirectionally:
- **Caller speaks** → Audio goes through bridge → External media channel → WebSocket → Voxtra → STT
- **AI responds** → TTS audio → WebSocket → External media channel → Bridge → Caller hears it

---

## DTMF: Touch-Tone Input

### What Is DTMF?

**Dual-Tone Multi-Frequency** is the system that generates tones when phone keys are pressed. Each key produces two simultaneous frequencies:

```
          1209 Hz  1336 Hz  1477 Hz  1633 Hz
697 Hz  │   1    │   2    │   3    │   A    │
770 Hz  │   4    │   5    │   6    │   B    │
852 Hz  │   7    │   8    │   9    │   C    │
941 Hz  │   *    │   0    │   #    │   D    │
```

For example, pressing "5" generates a tone combining 770 Hz and 1336 Hz.

### Why DTMF Matters for AI Agents

Even with conversational AI, DTMF is still important:

- **Fallback input** — Noisy environments where STT struggles, users can press keys
- **Confirmation** — "Press 1 to confirm your appointment"
- **Account numbers** — Safer to enter via keypad than speak aloud
- **IVR compatibility** — Integrating with existing phone systems that expect DTMF

In Voxtra, DTMF events are captured by the telephony adapter and pushed to the session's event queue as `DTMFEvent` objects.

---

## BaseTelephonyAdapter: The Abstract Interface

### Why an Abstraction?

Different PBX systems have very different APIs:

| PBX | Control Interface | Event Delivery | Media Bridge |
|-----|------------------|----------------|-------------|
| **Asterisk** | ARI REST API | ARI WebSocket | External Media + Bridge |
| **FreeSWITCH** | Event Socket Layer (ESL) | ESL events | Media bugs / uuid_bridge |
| **LiveKit** | LiveKit Server API + SDK | Room events / webhooks | LiveKit Rooms (WebRTC) |
| **Twilio** | REST API + TwiML | Webhooks | Media Streams (WebSocket) |

`BaseTelephonyAdapter` provides a **uniform interface** so the rest of Voxtra doesn't need to know which PBX is being used. The core application, router, sessions, and AI pipeline all work identically regardless of whether the backend is Asterisk, LiveKit, or anything else.

### The Interface

```python
class BaseTelephonyAdapter(ABC):

    # Lifecycle
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    # Event listening — the main event loop
    async def listen(self, callback: EventCallback) -> None: ...

    # Call control
    async def answer_call(self, channel_id: str) -> None: ...
    async def hangup_call(self, channel_id: str) -> None: ...
    async def transfer_call(self, channel_id: str, target: str) -> None: ...
    async def hold_call(self, channel_id: str) -> None: ...
    async def send_dtmf(self, channel_id: str, digits: str) -> None: ...

    # Media
    async def create_media_bridge(self, channel_id: str) -> str: ...
    async def play_audio(self, channel_id: str, audio_uri: str) -> None: ...
```

### Design Decisions

**Why `channel_id` as a string?** Different PBX systems identify channels differently (Asterisk uses `PJSIP/alice-00000001`, LiveKit uses room participant IDs). A string is the most universal representation.

**Why `listen()` takes a callback?** The adapter produces events asynchronously (from a WebSocket or event socket). Rather than returning a queue or iterator, it calls the provided callback for each event. This lets `VoxtraApp` wire the callback directly to its event dispatch chain including middleware.

**Why `create_media_bridge()` returns a string?** The return value is the media endpoint that the transport layer should connect to. For Asterisk, this is a host:port for the external media channel. For LiveKit, it would be a room identifier. The string keeps it generic.

---

## AsteriskARIAdapter: The Implementation

### Connection Lifecycle

```python
# 1. Connect — establish HTTP client for REST calls
adapter = AsteriskARIAdapter(config=asterisk_config)
await adapter.connect()
# → Creates httpx.AsyncClient with basic auth
# → Verifies connectivity by calling GET /ari/asterisk/info

# 2. Listen — start the event loop
await adapter.listen(callback=app._dispatch_event)
# → Opens WebSocket to ws://asterisk:8088/ari/events?app=voxtra
# → Loops forever, reading JSON events
# → Translates each event to a VoxtraEvent
# → Calls the callback for each event

# 3. Disconnect — clean shutdown
await adapter.disconnect()
# → Cancels the listen task
# → Closes WebSocket
# → Closes HTTP client
```

### Authentication

ARI uses **HTTP Basic Authentication**. The username and password are configured in Asterisk's `ari.conf`:

```ini
; /etc/asterisk/ari.conf
[asterisk]
type = user
password = secret
read_only = no
```

And in Voxtra's config:

```yaml
telephony:
  provider: asterisk
  asterisk:
    base_url: http://localhost:8088
    username: asterisk
    password: secret
    app_name: voxtra
```

The `websocket_url` is auto-derived from `base_url`:
```
http://localhost:8088 → ws://localhost:8088/ari/events?app=voxtra
```

### Event Translation

The adapter receives raw JSON events from the ARI WebSocket and translates them:

```json
// Raw ARI event (StasisStart):
{
  "type": "StasisStart",
  "timestamp": "2026-03-09T22:45:00.000+0200",
  "channel": {
    "id": "PJSIP/airtel-00000042",
    "state": "Ring",
    "caller": { "number": "+265888123456" },
    "dialplan": { "exten": "1000" }
  },
  "application": "voxtra"
}
```

Becomes:

```python
CallStartedEvent(
    session_id="PJSIP/airtel-00000042",
    caller_id="+265888123456",
    callee_id="1000",
    direction="inbound",
    data={"channel_id": "PJSIP/airtel-00000042", "raw": {...}}
)
```

### Error Handling

The adapter wraps all ARI operations with specific exceptions:

| Exception | When |
|-----------|------|
| `TelephonyConnectionError` | Cannot reach Asterisk ARI (wrong URL, auth failure, network) |
| `TelephonyError` | ARI REST call failed (invalid channel ID, bridge error, etc.) |

---

## LiveKit Adapter (Phase 2)

### What Is LiveKit?

LiveKit is an open-source WebRTC platform that provides:
- Real-time audio/video rooms
- Native SIP telephony integration (SIP trunks connect directly to LiveKit)
- Server-side agent framework (`livekit-agents`)
- Scalable, distributed media routing

### Why LiveKit for Voxtra?

| Feature | Asterisk | LiveKit |
|---------|----------|---------|
| **Deployment** | Self-hosted, Linux only | Cloud or self-hosted, any platform |
| **Scaling** | Single server, vertical | Distributed, horizontal |
| **Media routing** | Centralized | Distributed SFU |
| **Client SDKs** | SIP phones only | Web, mobile, server |
| **SIP support** | Native (it's a PBX) | Via SIP trunks + dispatch rules |

LiveKit is the planned production backend for large-scale deployments, while Asterisk is ideal for on-premise and development use cases.

### Current Status

The `LiveKitAdapter` implements the `BaseTelephonyAdapter` interface but raises `NotImplementedError` for all call control methods. Only `connect()` and `disconnect()` are functional, verifying API credentials. Full implementation is planned for Phase 2.

---

## Call Lifecycle in Detail

### Complete Inbound Call Flow

```
Step 1: Call arrives
─────────────────────
  Caller dials your number
  → SIP INVITE reaches Asterisk via SIP trunk
  → Asterisk creates channel PJSIP/trunk-00000001
  → Dialplan matches: exten => _X.,1,Stasis(voxtra)
  → Asterisk sends StasisStart event on ARI WebSocket

Step 2: Voxtra receives the event
──────────────────────────────────
  AsteriskARIAdapter._translate_event()
  → Creates CallStartedEvent(caller="+265888123456", callee="1000")
  → Passes to VoxtraApp._dispatch_event()
  → Event goes through middleware chain
  → Router.resolve() matches handler for extension "1000"
  → VoxtraApp creates CallSession
  → Handler runs as asyncio.Task

Step 3: Handler controls the call
─────────────────────────────────
  @app.route(extension="1000")
  async def support(session):

      # Answer the call (SIP 200 OK sent to caller)
      await session.answer()
      # → ARI POST /channels/PJSIP-trunk-00000001/answer

      # Set up media bridge for audio streaming
      # → ARI creates bridge + external media channel
      # → WebSocketMediaTransport connects to external media endpoint

      # Play greeting (TTS → media → caller hears it)
      await session.say("Hello, how can I help you?")

      # Listen for caller speech (media → STT → text)
      text = await session.listen(timeout=30)

      # AI generates response (text → LLM → response text)
      response = await session.agent.respond(text)

      # Play response (TTS → media → caller hears it)
      await session.say(response.text)

      # End the call
      await session.hangup()
      # → ARI DELETE /channels/PJSIP-trunk-00000001

Step 4: Cleanup
───────────────
  StasisEnd event received
  → CallEndedEvent dispatched
  → Session destroyed, resources released
```

---

## Dialplan Configuration

### Minimal Asterisk Setup for Voxtra

Asterisk needs a dialplan context that routes calls to the Stasis application:

```ini
; /etc/asterisk/extensions.conf

[voxtra-inbound]
; Route all extensions to Voxtra
exten => _X.,1,Stasis(voxtra)
 same => n,Hangup()
```

Pattern `_X.` matches any extension starting with a digit (0-9) followed by one or more characters. This catches all incoming calls.

For more selective routing:

```ini
[voxtra-inbound]
; Only route extensions 1000-1999 to Voxtra
exten => _1XXX,1,Stasis(voxtra)
 same => n,Hangup()

; Route everything else to a standard IVR
exten => _X.,1,Goto(standard-ivr,${EXTEN},1)
```

### SIP Trunk Configuration (PJSIP)

```ini
; /etc/asterisk/pjsip.conf

[airtel-trunk]
type = registration
outbound_auth = airtel-auth
server_uri = sip:sip.airtel.mw
client_uri = sip:your-account@sip.airtel.mw
retry_interval = 60

[airtel-auth]
type = auth
auth_type = userpass
username = your-account
password = your-password

[airtel-endpoint]
type = endpoint
context = voxtra-inbound     ; Route to Voxtra
transport = transport-udp
outbound_auth = airtel-auth
aors = airtel-aor
codecs = ulaw,alaw           ; G.711 codecs
```

### ARI Configuration

```ini
; /etc/asterisk/ari.conf

[general]
enabled = yes
pretty = yes

[asterisk]
type = user
read_only = no
password = secret
```

```ini
; /etc/asterisk/http.conf

[general]
enabled = yes
bindaddr = 0.0.0.0
bindport = 8088
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/voxtra/telephony/base.py` | `BaseTelephonyAdapter` abstract class and `EventCallback` type alias |
| `src/voxtra/telephony/asterisk/adapter.py` | `AsteriskARIAdapter` — Full ARI implementation (REST + WebSocket) |
| `src/voxtra/telephony/livekit/adapter.py` | `LiveKitAdapter` — Phase 2 stub |
| `src/voxtra/config.py` | `AsteriskConfig`, `LiveKitConfig`, `SIPTrunkConfig`, `TelephonyConfig` |
| `src/voxtra/events.py` | `CallStartedEvent`, `CallEndedEvent`, `DTMFEvent` and other event classes |
| `src/voxtra/exceptions.py` | `TelephonyError`, `TelephonyConnectionError` |
| `src/voxtra/types.py` | `CallDirection`, `CallState` enums |
