"""Asterisk ARI telephony adapter for Voxtra.

Connects to Asterisk via the Asterisk REST Interface (ARI)
for call control, media bridging, and event handling.
"""

from voxtra.telephony.asterisk.adapter import AsteriskARIAdapter

__all__ = ["AsteriskARIAdapter"]
