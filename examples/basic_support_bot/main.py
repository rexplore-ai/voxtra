"""Basic Support Bot — Voxtra example.

A simple AI-powered support agent that answers inbound calls
using Asterisk ARI + Deepgram STT + OpenAI GPT-4o + ElevenLabs TTS.

Usage:
    python main.py

Or with the CLI:
    voxtra start -c voxtra.yaml

Prerequisites:
    1. Asterisk running with ARI enabled
    2. Dialplan routing to Stasis(voxtra)
    3. Environment variables set:
       - DEEPGRAM_API_KEY
       - OPENAI_API_KEY
       - ELEVENLABS_API_KEY
"""

from __future__ import annotations

from voxtra import VoxtraApp, CallSession


app = VoxtraApp.from_yaml("voxtra.yaml")


@app.route(extension="1000")
async def support_call(session: CallSession) -> None:
    """Handle an inbound support call."""
    # Answer the call
    await session.answer()

    # Greet the caller
    await session.say(
        "Hello, welcome to Rexplore support. How can I help you today?"
    )

    # Conversation loop
    while True:
        # Listen for the caller's speech
        text = await session.listen(timeout=30.0)

        if not text:
            await session.say("Are you still there? I didn't catch that.")
            text = await session.listen(timeout=15.0)
            if not text:
                await session.say("It seems like you've stepped away. Goodbye!")
                break

        # Check for goodbye intent
        goodbye_words = {"bye", "goodbye", "thank you", "thanks", "that's all"}
        if any(word in text.lower() for word in goodbye_words):
            await session.say(
                "Thank you for calling. Have a wonderful day! Goodbye."
            )
            break

        # Check for transfer request
        if "transfer" in text.lower() or "human" in text.lower() or "agent" in text.lower():
            await session.say(
                "Let me transfer you to a human agent. One moment please."
            )
            await session.transfer("2000")
            return

        # Get AI response
        response = await session.agent.respond(text)
        await session.say(response.text)

    # Hang up
    await session.hangup()


@app.default_route()
async def fallback(session: CallSession) -> None:
    """Handle calls to unregistered extensions."""
    await session.answer()
    await session.say(
        "Sorry, the number you've reached is not available. "
        "Please try extension 1000 for support. Goodbye."
    )
    await session.hangup()


if __name__ == "__main__":
    app.run()
