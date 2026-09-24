import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from mqtt_handler import TinyGSMQTTClient


class TinyGSMQTTClientTests(unittest.TestCase):
    def setUp(self):
        self.tracker = MagicMock()
        self.handler = TinyGSMQTTClient(
            broker_url='mosquitto', broker_port=1883, device_id='My_TinyGS',
            plugin_id='3f2a-uuid', plugin_type='tinygs', publish_topic_base='plugin/3f2a-uuid/data',
            topic_prefix='pluto', tracker=self.tracker,
        )
        self.paho = MagicMock()

    def message(self, topic, payload):
        return SimpleNamespace(topic=topic, payload=payload)

    def test_topics_are_built_from_the_prefix(self):
        handler = TinyGSMQTTClient(
            broker_url='mosquitto', broker_port=1883, device_id='My_TinyGS',
            plugin_id='3f2a-uuid', plugin_type='tinygs', publish_topic_base='plugin/3f2a-uuid/data',
            topic_prefix='estacion',
        )

        self.assertEqual(handler.tracking_topic, 'estacion/My_TinyGS/tracking')
        self.assertEqual(handler.rx_topic, 'estacion/My_TinyGS/rx')

    def test_tracking_is_republished_and_handed_to_the_tracker(self):
        document = {'satellite': 'NOAA 19', 'NORAD': 33591}

        self.handler.on_message(self.paho, None, self.message('pluto/My_TinyGS/tracking', json.dumps(document).encode()))

        self.assertEqual(self.paho.publish.call_args.args[0], 'plugin/3f2a-uuid/data/tracking')
        self.tracker.on_tracking.assert_called_once_with(document)

    def test_rx_is_republished_but_never_reaches_the_tracker(self):
        self.handler.on_message(self.paho, None, self.message('pluto/My_TinyGS/rx', b'{"rssi": -97}'))

        self.assertEqual(self.paho.publish.call_args.args[0], 'plugin/3f2a-uuid/data/rx')
        self.tracker.on_tracking.assert_not_called()

    def test_a_tracking_payload_that_is_not_json_is_still_republished(self):
        with self.assertLogs('mqtt_handler', level='WARNING'):
            self.handler.on_message(self.paho, None, self.message('pluto/My_TinyGS/tracking', b'\xff\xfe'))

        self.paho.publish.assert_called_once()
        self.tracker.on_tracking.assert_not_called()

    def test_without_a_tracker_it_stays_a_republisher(self):
        handler = TinyGSMQTTClient(
            broker_url='mosquitto', broker_port=1883, device_id='My_TinyGS',
            plugin_id='3f2a-uuid', plugin_type='tinygs', publish_topic_base='plugin/3f2a-uuid/data',
        )

        handler.on_message(self.paho, None, self.message('pluto/My_TinyGS/tracking', b'{"NORAD": 33591}'))

        self.paho.publish.assert_called_once()

    def test_a_pass_is_published_with_qos_1(self):
        self.handler.client = MagicMock()

        self.handler.publish_coordinates('plugin/3f2a-uuid/coordinates/raw', '{"type": "ENU"}')

        self.handler.client.publish.assert_called_once_with(
            'plugin/3f2a-uuid/coordinates/raw', '{"type": "ENU"}', qos=1,
        )


if __name__ == '__main__':
    unittest.main()
