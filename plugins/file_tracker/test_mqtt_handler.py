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
        self.handler = FileTrackerMQTTClient(
            broker_url='mosquitto', broker_port=1883,
            input_topic='plugin/3f2a/input/file', publish_topic='plugin/3f2a/coordinates/raw',
            station=Station(lat=0, lon=0, alt=0),
        )
        self.paho = MagicMock()

    def receive(self, payload):
        self.handler.on_message(self.paho, None, SimpleNamespace(topic='plugin/3f2a/input/file', payload=payload))

    def test_an_upload_is_published_as_raw_coordinates(self):
        self.receive(upload())

        topic, body = self.paho.publish.call_args.args
        self.assertEqual(topic, 'plugin/3f2a/coordinates/raw')
        self.assertEqual(len(json.loads(body)['coordinates']), 2)

    def test_the_retained_file_is_not_published_again_on_reconnection(self):
        self.receive(upload())
        self.receive(upload())

        self.assertEqual(self.paho.publish.call_count, 1)

    def test_a_new_upload_is_published(self):
        self.receive(upload('u-1'))
        self.receive(upload('u-2'))

        self.assertEqual(self.paho.publish.call_count, 2)

    def test_a_bad_file_is_discarded_and_the_next_one_still_works(self):
        self.receive(upload('u-1', content='no coordinates'))
        self.receive(b'not json')
        self.receive(upload('u-2'))

        self.assertEqual(self.paho.publish.call_count, 1)

    def test_a_cleared_file_publishes_nothing(self):
        self.receive(b'')

        self.paho.publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
