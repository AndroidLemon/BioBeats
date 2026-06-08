# Mirrors every OSC send to several underlying senders — lets one control
# stream (e.g. the MIDI bridge's translated messages, or a future biometric
# control surface) drive multiple listeners in lockstep: the RT2 OSC bridge
# AND a visuals relay (e.g. hydra-osc, feeding Hydra) at once.
#
# Pure composition over OSCSenderProtocol — a fanout sender is itself just
# another OSC sender, so it drops into any adapter (MIDIBridge, etc.) with no
# changes to that adapter or to the listeners on the other end.

from src.integrations.osc_client import OSCSenderProtocol


class FanoutOSCSender:
    """Forwards every send() to each wrapped sender, in order."""

    def __init__(self, senders: list[OSCSenderProtocol]) -> None:
        self._senders = list(senders)

    def send(self, address: str, value) -> None:
        """Forward (address, value) to every wrapped sender, in order."""
        for sender in self._senders:
            sender.send(address, value)
