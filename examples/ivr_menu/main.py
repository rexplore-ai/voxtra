"""IVR Menu example — multi-option phone menu with DTMF routing.

Demonstrates:
- Extension-based routing
- DTMF input collection
- Transfer to queue (human handoff)
- Call recording

Requirements:
    - Asterisk with ARI enabled
    - Dialplan routing calls to Stasis(voxtra)
"""

from voxtra import VoxtraApp

app = VoxtraApp(
    ari_url="http://localhost:8088",
    ari_user="asterisk",
    ari_password="secret",
)


@app.on_call
async def main_menu(call):
    """Main IVR menu — plays options and routes based on DTMF."""
    await call.answer()

    # Start recording the call
    await call.record_start()

    # Play greeting
    await call.play_file("welcome")
    await call.play_file("press-1")  # "Press 1 for support"
    await call.play_file("press-2")  # "Press 2 for sales"

    # Collect a single DTMF digit
    digit = await call.listen_dtmf(max_digits=1, timeout=10.0)

    if digit == "1":
        # Transfer to support queue with context
        await call.transfer_to_queue("support", metadata={
            "source": "ivr",
            "intent": "support",
        })
    elif digit == "2":
        # Transfer to sales queue
        await call.transfer_to_queue("sales", metadata={
            "source": "ivr",
            "intent": "sales",
        })
    else:
        # No valid input — play error and retry
        await call.play_file("invalid-option")
        await call.hangup()


app.run()
