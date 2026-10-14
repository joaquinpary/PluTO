import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from models import Station
from mqtt_handler import FileTrackerMQTTClient


def upload(upload_id='u-1', content='40 -3 667\n41 2 12\n', coord_type='ECEF', coord_format='GEO'):
    return json.dumps({
        'upload_id': upload_id, 'filename': 'coords.txt',
        'coord_type': coord_type, 'coord_format': coord_format, 'content': content,
    }).encode()


class FileTrackerMQTTClientTests(unittest.TestCase):
    def setUp(self):
        self.antenna = MagicMock()
        self.handler = FileTrackerMQTTClient(
            broker_url='mosquitto', broker_port=1883,
            input_topic='plugin/3f2a/input/file',
            station=Station(lat=0, lon=0, alt=0), antenna=self.antenna,
        )
        self.paho = MagicMock()

    def receive(self, payload):
        self.handler.on_message(self.paho, None, SimpleNamespace(topic='plugin/3f2a/input/file', payload=payload))

    def test_an_upload_goes_to_the_antenna_as_a_raw_trajectory(self):
        self.receive(upload())

        (raw,) = self.antenna.submit.call_args.args
        self.assertEqual((raw['type'], raw['coord_format']), ('ECEF', 'GEO'))
        self.assertEqual(len(raw['coordinates']), 2)
        # JSON-ready, as POST /transform takes it.
        json.dumps(raw)
        # Nothing goes on the broker any more: the antenna owns the board's topic.
        self.paho.publish.assert_not_called()

    def test_the_retained_file_is_not_pointed_at_again_on_reconnection(self):
        self.receive(upload())
        self.receive(upload())

        self.assertEqual(self.antenna.submit.call_count, 1)

    def test_a_new_upload_is_pointed_at(self):
        self.receive(upload('u-1'))
        self.receive(upload('u-2'))

        self.assertEqual(self.antenna.submit.call_count, 2)

    def test_a_bad_file_is_discarded_and_the_next_one_still_works(self):
        self.receive(upload('u-1', content='no coordinates'))
        self.receive(b'not json')
        self.receive(upload('u-2'))

        self.assertEqual(self.antenna.submit.call_count, 1)

    def test_a_cleared_file_points_at_nothing(self):
        self.receive(b'')

        self.antenna.submit.assert_not_called()

    def test_without_a_board_a_file_is_parsed_but_not_pointed_at(self):
        self.handler.antenna = None

        with self.assertLogs('mqtt_handler', level='WARNING'):
            self.receive(upload())

    def test_a_board_message_goes_with_qos_1_and_is_never_retained(self):
        self.handler.client = MagicMock()

        self.handler.publish_to_board('device/a1b2c3d4e5f6/coordinates/polar', b'\x50\x01')

        self.handler.client.publish.assert_called_once_with(
            'device/a1b2c3d4e5f6/coordinates/polar', b'\x50\x01', qos=1, retain=False,
        )

    def test_without_a_board_it_subscribes_to_its_input_only(self):
        self.handler.on_connect(self.paho, None, None, SimpleNamespace(is_failure=False), None)

        self.paho.subscribe.assert_called_once_with([('plugin/3f2a/input/file', 1)])

    def test_with_a_board_it_forwards_the_board_reports(self):
        bridge = MagicMock()
        bridge.subscriptions.return_value = [('device/a1b2c3d4e5f6/status', 1), ('device/a1b2c3d4e5f6/state', 0)]
        bridge.handles.side_effect = lambda topic: topic.startswith('device/')
        self.handler.bridge = bridge

        self.handler.on_connect(self.paho, None, None, SimpleNamespace(is_failure=False), None)
        self.handler.on_message(self.paho, None, SimpleNamespace(topic='device/a1b2c3d4e5f6/status', payload=b'online'))

        self.assertIn(('device/a1b2c3d4e5f6/status', 1), self.paho.subscribe.call_args.args[0])
        bridge.forward.assert_called_once_with('device/a1b2c3d4e5f6/status', b'online')
        self.paho.publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
