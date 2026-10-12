import io
import json
import unittest
import urllib.error

from pluto_sdk.api_client import DONE, DROP, RETRY, ApiClient, backoff, classify


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeServer:
    """Answers each request with the next of `answers`: a status code, or an exception."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if answer >= 400:
            raise urllib.error.HTTPError(request.full_url, answer, 'error', {}, io.BytesIO(b'{"detail": "no"}'))
        return FakeResponse(answer)


def client(server, sleeps=None):
    return ApiClient('http://server:8000/api/', 'pluto_secret', urlopen=server,
                     sleep=(sleeps.append if sleeps is not None else lambda _: None))


def next_item(api):
    return api._queue.get_nowait()


class ClassifyTests(unittest.TestCase):
    def test_success_is_done(self):
        self.assertEqual(classify(200), DONE)
        self.assertEqual(classify(201), DONE)

    def test_what_can_pass_is_retried(self):
        for status in (None, 401, 408, 429, 500, 503):
            self.assertEqual(classify(status), RETRY, status)

    def test_a_wrong_request_is_dropped(self):
        for status in (400, 403, 404, 413, 415):
            self.assertEqual(classify(status), DROP, status)

    def test_backoff_doubles_up_to_a_cap(self):
        self.assertEqual([backoff(attempt) for attempt in range(8)], [1, 2, 4, 8, 16, 32, 60, 60])


class ApiClientTests(unittest.TestCase):
    def test_posts_an_envelope_with_the_plugin_token(self):
        server = FakeServer(201)
        api = client(server)

        api.send_data('rx', {'message_id': 'm-1', 'payload': {'rssi': -97}})
        outcome = api.deliver(next_item(api))

        self.assertEqual(outcome, DONE)
        request = server.requests[0]
        self.assertEqual(request.full_url, 'http://server:8000/api/plugin-data/rx')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Plugin pluto_secret')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data), {'message_id': 'm-1', 'payload': {'rssi': -97}})

    def test_board_reports_go_as_the_board_sent_them(self):
        server = FakeServer(201, 201)
        api = client(server)

        api.send_device('status', b'online')
        api.send_device('state', b'{"mode": "idle"}')
        api.deliver(next_item(api))
        api.deliver(next_item(api))

        status, state = server.requests
        self.assertEqual((status.full_url, status.data, status.get_header('Content-type')),
                         ('http://server:8000/api/device/status', b'online', 'text/plain'))
        self.assertEqual((state.full_url, state.data, state.get_header('Content-type')),
                         ('http://server:8000/api/device/state', b'{"mode": "idle"}', 'application/json'))

    def test_retries_until_the_server_is_back(self):
        sleeps = []
        server = FakeServer(urllib.error.URLError('refused'), 503, 401, 201)
        api = client(server, sleeps)

        api.send_data('rx', {'message_id': 'm-1'})
        with self.assertLogs('pluto_sdk.api_client', level='WARNING'):
            outcome = api.deliver(next_item(api))

        self.assertEqual(outcome, DONE)
        self.assertEqual(len(server.requests), 4)
        self.assertEqual(sleeps, [1, 2, 4])

    def test_a_rejected_request_is_not_retried(self):
        server = FakeServer(400)
        api = client(server)

        api.send_data('rx', {'message_id': 'm-1'})
        with self.assertLogs('pluto_sdk.api_client', level='ERROR'):
            outcome = api.deliver(next_item(api))

        self.assertEqual(outcome, DROP)
        self.assertEqual(len(server.requests), 1)

    def test_a_full_queue_drops_the_newest_and_says_so(self):
        api = ApiClient('http://server:8000/api/', 'pluto_secret', max_queue=1)

        self.assertTrue(api.send_data('rx', {'message_id': 'kept'}))
        with self.assertLogs('pluto_sdk.api_client', level='ERROR'):
            self.assertFalse(api.send_data('rx', {'message_id': 'dropped'}))

    def test_the_worker_delivers_in_order(self):
        server = FakeServer(201, 201, 201)
        api = client(server)
        api.start()

        for index in range(3):
            api.send_data('rx', {'message_id': f'm-{index}'})
        # stop() queues its marker behind the three, so they are all sent first.
        api.stop(timeout=2)

        self.assertEqual([json.loads(request.data)['message_id'] for request in server.requests],
                         ['m-0', 'm-1', 'm-2'])


if __name__ == '__main__':
    unittest.main()
