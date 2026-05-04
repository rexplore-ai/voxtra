"""AI Voice Agent example — STT + LLM + TTS over AudioSocket.

Demonstrates:
- AudioSocket bidirectional audio streaming
- Integration with Deepgram (STT), OpenAI (LLM), ElevenLabs (TTS)
- Barge-in handling
- Human handoff when AI can't resolve

Requirements:
    pip install voxtra deepgram-sdk openai elevenlabs
"""

import os

from voxtra import VoxtraApp, AudioChunk

app = VoxtraApp(
    ari_url=os.environ.get("VOXTRA_ARI_URL", "http://localhost:8088"),
    ari_user=os.environ.get("VOXTRA_ARI_USER", "asterisk"),
    ari_password=os.environ.get("VOXTRA_ARI_PASSWORD", "secret"),
)


@app.on_call
async def ai_agent(call):
    """AI-powered voice agent that handles customer calls."""
    await call.answer()
    await call.record_start()

    # Open bidirectional audio stream via AudioSocket
    audio_conn = await call.open_audio_socket()

    # In a real application, you would wire this up to your
    # STT → LLM → TTS pipeline. Here's the pattern:
    #
    #   async for chunk in audio_conn.receive():
    #       # 1. Feed audio to STT (e.g. Deepgram)
    #       transcript = await stt.transcribe(chunk.data)
    #
    #       if transcript.is_final:
    #           # 2. Send transcript to LLM
    #           response = await llm.respond(transcript.text)
    #
    #           # 3. Synthesize response to audio
    #           async for audio in tts.synthesize(response.text):
    #               await audio_conn.send(audio)
    #
    # For now, we just play a greeting and listen for DTMF:
    await call.play_file("hello-world")

    # Wait for caller to press a key
    digit = await call.listen_dtmf(max_digits=1, timeout=30.0)

    if digit == "0":
        # Transfer to human agent
        await call.transfer_to_queue("support", metadata={
            "source": "ai_agent",
            "summary": "Caller requested human agent",
        })
    else:
        await call.play_file("goodbye")
        await call.hangup()


app.run()
