import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from mqtt_handler import TinyGSMQTTClient


class TinyGSMQTTClientTests(unittest.TestCase):
    def setUp(self):
        self.tracker = MagicMock()
        self.api = MagicMock()
        self.handler = TinyGSMQTTClient(
            broker_url='mosquitto', broker_port=1883, device_id='My_TinyGS',
            plugin_id='3f2a-uuid', plugin_type='tinygs', api=self.api,
            topic_prefix='pluto', tracker=self.tracker,
        )
        self.paho = MagicMock()

    def message(self, topic, payload):
        return SimpleNamespace(topic=topic, payload=payload)

    def test_topics_are_built_from_the_prefix(self):
        handler = TinyGSMQTTClient(
            broker_url='mosquitto', broker_port=1883, device_id='My_TinyGS',
            plugin_id='3f2a-uuid', plugin_type='tinygs', api=MagicMock(),
            topic_prefix='estacion',
        )

        self.assertEqual(handler.tracking_topic, 'estacion/My_TinyGS/tracking')
        self.assertEqual(handler.rx_topic, 'estacion/My_TinyGS/rx')

    def test_tracking_goes_to_the_server_and_to_the_tracker(self):
        document = {'satellite': 'NOAA 19', 'NORAD': 33591}

        self.handler.on_message(self.paho, None, self.message('pluto/My_TinyGS/tracking', json.dumps(document).encode()))

        message_type, envelope = self.api.send_data.call_args.args
        self.assertEqual(message_type, 'tracking')
        self.assertEqual(envelope['payload'], document)
        self.assertEqual(envelope['source_topic'], 'pluto/My_TinyGS/tracking')
        self.tracker.on_tracking.assert_called_once_with(document)
        # Nothing goes back to the broker any more.
        self.paho.publish.assert_not_called()

    def test_rx_goes_to_the_server_but_never_reaches_the_tracker(self):
        self.handler.on_message(self.paho, None, self.message('pluto/My_TinyGS/rx', b'{"rssi": -97}'))

        self.assertEqual(self.api.send_data.call_args.args[0], 'rx')
        self.tracker.on_tracking.assert_not_called()

    def test_a_tracking_payload_that_is_not_json_still_goes_to_the_server(self):
        with self.assertLogs('mqtt_handler', level='WARNING'):
            self.handler.on_message(self.paho, None, self.message('pluto/My_TinyGS/tracking', b'\xff\xfe'))

        self.api.send_data.assert_called_once()
        self.tracker.on_tracking.assert_not_called()

    def test_without_a_tracker_it_stays_a_relay(self):
        api = MagicMock()
        handler = TinyGSMQTTClient(
            broker_url='mosquitto', broker_port=1883, device_id='My_TinyGS',
            plugin_id='3f2a-uuid', plugin_type='tinygs', api=api,
        )

        handler.on_message(self.paho, None, self.message('pluto/My_TinyGS/tracking', b'{"NORAD": 33591}'))

        api.send_data.assert_called_once()

    def test_without_a_board_it_subscribes_to_the_station_only(self):
        self.handler.on_connect(self.paho, None, None, 0)

        self.paho.subscribe.assert_called_once_with([('pluto/My_TinyGS/tracking', 1), ('pluto/My_TinyGS/rx', 1)])

    def test_with_a_board_it_also_listens_to_it_and_forwards_its_reports(self):
        bridge = MagicMock()
        bridge.subscriptions.return_value = [('device/a1b2c3d4e5f6/status', 1), ('device/a1b2c3d4e5f6/state', 0)]
        bridge.handles.side_effect = lambda topic: topic.startswith('device/')
        self.handler.bridge = bridge

        self.handler.on_connect(self.paho, None, None, 0)
        self.handler.on_message(self.paho, None, self.message('device/a1b2c3d4e5f6/state', b'{"mode": "idle"}'))

        self.assertIn(('device/a1b2c3d4e5f6/state', 0), self.paho.subscribe.call_args.args[0])
        bridge.forward.assert_called_once_with('device/a1b2c3d4e5f6/state', b'{"mode": "idle"}')
        # A board report is not station data.
        self.api.send_data.assert_not_called()
        self.tracker.on_tracking.assert_not_called()

    def test_a_board_message_goes_with_qos_1_and_is_never_retained(self):
        self.handler.client = MagicMock()

        self.handler.publish_to_board('device/a1b2c3d4e5f6/coordinates/polar', b'\x50\x01')

        self.handler.client.publish.assert_called_once_with(
            'device/a1b2c3d4e5f6/coordinates/polar', b'\x50\x01', qos=1, retain=False,
        )


if __name__ == '__main__':
    unittest.main()
