"""Minimal Voxtra example — 10 lines to a working call handler.

This is the simplest possible Voxtra application. It answers
incoming calls, plays a greeting, and hangs up.

Requirements:
    - Asterisk with ARI enabled
    - Dialplan routing calls to Stasis(voxtra)

    pip install voxtra
"""

from voxtra import VoxtraApp

app = VoxtraApp(
    ari_url="http://localhost:8088",
    ari_user="asterisk",
    ari_password="secret",
)


@app.on_call
async def handle(call):
    await call.answer()
    await call.play_file("hello-world")
    await call.hangup()


app.run()
