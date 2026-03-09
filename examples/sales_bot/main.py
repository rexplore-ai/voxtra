"""Sales Bot — Voxtra example.

An AI-powered outbound sales agent that qualifies leads,
introduces Voxtra, and offers to schedule demos.

Uses Asterisk ARI + Deepgram STT + OpenAI GPT-4o + ElevenLabs TTS.

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


@app.route(extension="2000")
async def sales_call(session: CallSession) -> None:
    """Handle an outbound sales call."""
    await session.answer()

    # Opening pitch — keep it short and friendly
    await session.say(
        "Hi there! This is Alex from Rexplore Labs. "
        "I'm reaching out because I think our platform, Voxtra, "
        "could really help your business. Do you have a quick minute?"
    )

    text = await session.listen(timeout=15.0)

    if not text:
        await session.say(
            "No worries, seems like it's not a good time. "
            "Have a great day! Goodbye."
        )
        await session.hangup()
        return

    # Check if they're not interested upfront
    not_interested = {"no", "not interested", "busy", "don't call", "remove"}
    if any(phrase in text.lower() for phrase in not_interested):
        await session.say(
            "Totally understand. Thanks for your time, "
            "and I hope you have a great day. Goodbye!"
        )
        await session.hangup()
        return

    # Qualification conversation loop
    max_turns = 10
    turn = 0

    while turn < max_turns:
        # Get AI response (the LLM drives the conversation)
        response = await session.agent.respond(text)
        await session.say(response.text)

        # Check if the AI decided to wrap up
        wrap_up = {"goodbye", "have a great day", "talk soon", "take care"}
        if any(phrase in response.text.lower() for phrase in wrap_up):
            break

        # Listen for the prospect's reply
        text = await session.listen(timeout=20.0)

        if not text:
            await session.say("Are you still there?")
            text = await session.listen(timeout=10.0)
            if not text:
                await session.say(
                    "It sounds like you might have stepped away. "
                    "Thanks for your time! Goodbye."
                )
                break

        # Check for ending signals from the prospect
        goodbye_words = {"bye", "goodbye", "not interested", "no thanks"}
        if any(word in text.lower() for word in goodbye_words):
            await session.say(
                "Thanks so much for your time today. "
                "If you ever want to learn more, don't hesitate to reach out. "
                "Have a wonderful day!"
            )
            break

        turn += 1

    await session.hangup()


@app.default_route()
async def fallback(session: CallSession) -> None:
    """Handle calls to unregistered extensions."""
    await session.answer()
    await session.say(
        "Sorry, the number you've reached is not available. "
        "Please try extension 2000 for our sales team. Goodbye."
    )
    await session.hangup()


if __name__ == "__main__":
    app.run()
