"""Forwards the reports of the board bound to a plugin instance to the server.

The board keeps publishing on MQTT (docs/contracts/device-state.md) and does
not know who listens. The plugin that drives it is the one that listens now,
and only to that board: its MAC arrives as ROTOR_DEVICE_ID when the plugin is
launched. The server stores the report under the board bound to the plugin's
token, so the payload is forwarded exactly as the board sent it.
"""
import re

DEVICE_ID_RE = re.compile(r'[0-9a-f]{12}')


class BoardBridge:
    def __init__(self, device_id, api):
        if not DEVICE_ID_RE.fullmatch(device_id):
            raise ValueError(f'ROTOR_DEVICE_ID must be twelve lowercase hex digits, got {device_id!r}')
        self.device_id = device_id
        self.api = api
        self._leaves = {
            f'device/{device_id}/status': 'status',
            f'device/{device_id}/state': 'state',
        }

    def subscriptions(self):
        """(topic, qos) pairs to add to the plugin's subscribe call.

        The QoS the board publishes each one with. status is retained, so the
        current one arrives right after subscribing, on every reconnection; the
        server only moves status_changed_at on a real change.
        """
        return [(f'device/{self.device_id}/status', 1), (f'device/{self.device_id}/state', 0)]

    def handles(self, topic):
        return topic in self._leaves

    def forward(self, topic, payload):
        self.api.send_device(self._leaves[topic], payload)
