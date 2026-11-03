import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock

from pluto_sdk import ConfigurationError, antenna_from_environment
from pluto_sdk.antenna import Antenna
from pluto_sdk.api_client import ApiClient, ApiError
from pluto_sdk.pointing import RotorLimits
from pluto_sdk.transform_client import TransformClient, TransformError
from test_api_client import FakeResponse
from test_pointing import DEVICE_ID, at, polar, rising_pass

RAW = {'type': 'ENU', 'coord_format': 'POLAR', 'station': {'lat': 0, 'lon': 0, 'alt': 0}, 'coordinates': []}
ROTOR = {'device_id': DEVICE_ID, 'min_elevation_deg': 10.0, 'min_azimuth_deg': None, 'max_azimuth_deg': None}


class JsonResponse(FakeResponse):
    def __init__(self, status, document):
        super().__init__(status)
        self.body = json.dumps(document).encode()

    def read(self):
        return self.body


def http_error(url, status, body=b'{"detail": "no"}'):
    return urllib.error.HTTPError(url, status, 'error', {}, io.BytesIO(body))


class AntennaTests(unittest.TestCase):
    def setUp(self):
        self.api = MagicMock()
        self.api.get_rotor.return_value = ROTOR
        self.transform = MagicMock()
        self.transform.transform.return_value = polar(rising_pass())
        self.dispatcher = MagicMock()
        self.antenna = Antenna(self.api, self.transform, self.dispatcher, sleep=lambda _: None)

    def test_transforms_asks_for_the_limits_and_plans(self):
        self.antenna.process(RAW)

        self.transform.transform.assert_called_once_with(RAW)
        limits, trajectory = self.dispatcher.install.call_args.args
        self.assertEqual(limits, RotorLimits(DEVICE_ID, 10.0))
        self.assertEqual(trajectory, rising_pass())

    def test_the_limits_are_asked_for_every_trajectory(self):
        self.antenna.process(RAW)
        self.antenna.process(RAW)

        self.assertEqual(self.api.get_rotor.call_count, 2)

    def test_a_trajectory_coord_transform_rejects_is_dropped(self):
        self.transform.transform.side_effect = TransformError('422')

        with self.assertLogs('pluto_sdk.antenna', level='ERROR'):
            self.assertFalse(self.antenna.process(RAW))

        self.dispatcher.install.assert_not_called()

    def test_without_a_board_nothing_is_planned(self):
        self.api.get_rotor.return_value = None

        with self.assertLogs('pluto_sdk.antenna', level='INFO'):
            self.assertFalse(self.antenna.process(RAW))

        self.dispatcher.install.assert_not_called()

    def test_the_limits_are_retried_and_then_given_up(self):
        self.api.get_rotor.side_effect = [ApiError('down'), ApiError('down'), ROTOR]

        with self.assertLogs('pluto_sdk.antenna', level='WARNING'):
            self.antenna.process(RAW)

        self.dispatcher.install.assert_called_once()

        self.api.get_rotor.side_effect = ApiError('down')
        with self.assertLogs('pluto_sdk.antenna', level='WARNING'):
            self.assertFalse(self.antenna.process(RAW))

    def test_stopping_holds_the_antenna(self):
        self.antenna.stop()

        self.dispatcher.stop.assert_called_once()

    def test_a_full_queue_drops_the_newest_and_says_so(self):
        antenna = Antenna(self.api, self.transform, self.dispatcher, max_pending=1)

        self.assertTrue(antenna.submit(RAW))
        with self.assertLogs('pluto_sdk.antenna', level='ERROR'):
            self.assertFalse(antenna.submit(RAW))

    def test_the_worker_survives_an_unexpected_error(self):
        self.dispatcher.install.side_effect = [RuntimeError('bug'), True]
        self.antenna.start()

        with self.assertLogs('pluto_sdk.antenna', level='ERROR'):
            self.antenna.submit(RAW)
            self.antenna.submit(RAW)
            self.antenna.stop()
            self.antenna._thread.join(2)

        self.assertEqual(self.dispatcher.install.call_count, 2)


class TransformClientTests(unittest.TestCase):
    def test_posts_the_raw_trajectory_and_returns_the_polar_one(self):
        requests = []

        def urlopen(request, timeout):
            requests.append(request)
            return JsonResponse(200, polar(rising_pass(1)))

        result = TransformClient('http://coord_transform:8000/', urlopen=urlopen).transform(RAW)

        self.assertEqual(result, polar(rising_pass(1)))
        self.assertEqual(requests[0].full_url, 'http://coord_transform:8000/transform')
        self.assertEqual(json.loads(requests[0].data), RAW)

    def test_retries_while_coord_transform_is_down(self):
        answers = [urllib.error.URLError('refused'), http_error('u', 503), JsonResponse(200, {'coordinates': []})]
        sleeps = []

        def urlopen(request, timeout):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        client = TransformClient('http://t/', urlopen=urlopen, sleep=sleeps.append)
        with self.assertLogs('pluto_sdk.transform_client', level='WARNING'):
            self.assertEqual(client.transform(RAW), {'coordinates': []})
        self.assertEqual(sleeps, [1, 2])

    def test_a_rejected_trajectory_is_not_retried(self):
        calls = []

        def urlopen(request, timeout):
            calls.append(request)
            raise http_error(request.full_url, 422, b'{"detail": "bad type"}')

        with self.assertRaisesRegex(TransformError, 'bad type'):
            TransformClient('http://t/', urlopen=urlopen).transform(RAW)
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_its_attempts(self):
        def urlopen(request, timeout):
            raise urllib.error.URLError('refused')

        client = TransformClient('http://t/', attempts=3, urlopen=urlopen, sleep=lambda _: None)
        with self.assertLogs('pluto_sdk.transform_client', level='WARNING'), self.assertRaises(TransformError):
            client.transform(RAW)


class ApiClientPointingTests(unittest.TestCase):
    def test_get_rotor_returns_the_board_or_none(self):
        requests = []

        def urlopen(request, timeout):
            requests.append(request)
            return JsonResponse(200, ROTOR if len(requests) == 1 else None)

        api = ApiClient('http://server:8000/api/', 'pluto_secret', urlopen=urlopen)

        self.assertEqual(api.get_rotor(), ROTOR)
        self.assertIsNone(api.get_rotor())
        self.assertEqual(requests[0].full_url, 'http://server:8000/api/plugin/rotor')
        self.assertEqual(requests[0].get_header('Authorization'), 'Plugin pluto_secret')

    def test_get_rotor_raises_when_the_server_does_not_answer(self):
        def urlopen(request, timeout):
            raise http_error(request.full_url, 503)

        with self.assertRaises(ApiError) as caught:
            ApiClient('http://server:8000/api/', 't', urlopen=urlopen).get_rotor()
        self.assertEqual(caught.exception.status, 503)

    def test_dispatch_orders_are_queued_for_the_server(self):
        requests = []

        def urlopen(request, timeout):
            requests.append(request)
            return FakeResponse(201)

        api = ApiClient('http://server:8000/api/', 't', urlopen=urlopen)
        order = {'kind': 'HOLD', 't0_ms': at(0), 't_sent_ms': at(0), 'points': [], 'reason': 'stopped'}

        api.send_dispatch_order(order)
        api.deliver(api._queue.get_nowait())

        self.assertEqual(requests[0].full_url, 'http://server:8000/api/dispatch-orders')
        self.assertEqual(json.loads(requests[0].data), order)


class AntennaFromEnvironmentTests(unittest.TestCase):
    ENV = {'PLUTO_TRANSFORM_URL': 'http://coord_transform:8000/', 'ROTOR_DEVICE_ID': DEVICE_ID}

    def test_without_a_board_there_is_no_antenna(self):
        self.assertIsNone(antenna_from_environment(MagicMock(), MagicMock(), {}))

    def test_with_a_board_it_publishes_through_the_plugin_and_reports_through_the_api(self):
        api, publish = MagicMock(), MagicMock()

        antenna = antenna_from_environment(api, publish, dict(self.ENV))
        antenna.stop()
        antenna._thread.join(2)

        self.assertEqual(antenna.transform.url, 'http://coord_transform:8000/transform')
        self.assertIs(antenna.dispatcher._publish, publish)
        self.assertEqual(antenna.dispatcher._report, api.send_dispatch_order)

    def test_a_board_without_the_transform_url_is_a_configuration_error(self):
        with self.assertRaises(ConfigurationError):
            antenna_from_environment(MagicMock(), MagicMock(), {'ROTOR_DEVICE_ID': DEVICE_ID})


if __name__ == '__main__':
    unittest.main()
