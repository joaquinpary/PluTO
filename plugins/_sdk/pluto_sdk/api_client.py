"""Hands what a plugin produces to the server's /api/ (docs/contracts/ingest-api.md).

The callers are MQTT callbacks, and those must never wait on HTTP: a slow
server would stall the network loop and with it every subscription. So sending
only queues the request, and one worker thread posts them in order. The order
matters for a board's reports, where a later state must not land first.

Retrying replaces what QoS 1 on the broker used to give: a request that failed
for a reason that can pass (the server restarting, the network) is tried again
with a growing pause. That is safe because the server answers a repeated
message_id as a duplicate instead of storing it twice. What is still lost is
whatever sits in the queue when the container dies.

Standard library only, so every plugin image can carry it without a new dependency.
"""
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DONE = 'done'
DROP = 'drop'
RETRY = 'retry'


def classify(status):
    """What to do after an HTTP status. None means the request never got an answer."""
    if status is None:
        return RETRY
    if 200 <= status < 300:
        return DONE
    # 401 can pass: the server records the token's hash right after the
    # container is started, so the first requests may beat it. A container
    # whose instance was stopped is removed with it, so it does not retry forever.
    if status in (401, 408, 429) or status >= 500:
        return RETRY
    # Any other 4xx means the request itself is wrong; sending it again will not help.
    return DROP


def backoff(attempt, base=1.0, cap=60.0):
    """Seconds to wait before retry number `attempt` (0, 1, 2...): 1, 2, 4... up to cap."""
    return min(cap, base * (2 ** attempt))


class ApiClient:
    def __init__(self, base_url, token, max_queue=1000, timeout=10.0,
                 urlopen=urllib.request.urlopen, sleep=time.sleep):
        self.base_url = base_url.rstrip('/') + '/'
        self.token = token
        self.timeout = timeout
        self._urlopen = urlopen
        self._sleep = sleep
        # Bounded: if the server is down for long, the plugin drops the newest
        # messages and says so, rather than growing until the container is killed.
        self._queue = queue.Queue(maxsize=max_queue)
        self._stopping = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name='pluto-api', daemon=True)
        self._thread.start()

    def stop(self, timeout=5.0):
        self._stopping.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout)

    def send_data(self, message_type, envelope):
        """Queue one envelope for POST /api/plugin-data/<message_type>."""
        return self._enqueue(
            f'plugin-data/{message_type}',
            json.dumps(envelope).encode('utf-8'),
            'application/json',
            f'{message_type} {envelope.get("message_id")}',
        )

    def send_device(self, leaf, raw):
        """Queue a board report for POST /api/device/<status|state>, as the board sent it."""
        content_type = 'text/plain' if leaf == 'status' else 'application/json'
        return self._enqueue(f'device/{leaf}', raw, content_type, f'device {leaf}')

    def _enqueue(self, path, body, content_type, label):
        try:
            self._queue.put_nowait((path, body, content_type, label))
        except queue.Full:
            logger.error('API queue full, dropping %s', label)
            return False
        return True

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            self.deliver(item)

    def deliver(self, item):
        """Post one queued request until it is done or not worth retrying. Returns the outcome."""
        path, body, content_type, label = item
        attempt = 0
        while True:
            status = self._post(path, body, content_type, label)
            outcome = classify(status)
            if outcome == DONE:
                logger.debug('%s -> %s', label, status)
                return DONE
            if outcome == DROP:
                logger.error('Server rejected %s with %s, not retrying', label, status)
                return DROP
            if self._stopping.is_set():
                return RETRY

            pause = backoff(attempt)
            logger.warning('Could not deliver %s (status %s), retrying in %ss', label, status, pause)
            self._sleep(pause)
            attempt += 1

    def _post(self, path, body, content_type, label):
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method='POST',
            headers={'Authorization': f'Plugin {self.token}', 'Content-Type': content_type},
        )
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode('utf-8', errors='replace')
            logger.info('%s answered %s: %s', label, exc.code, detail)
            return exc.code
        except (urllib.error.URLError, OSError) as exc:
            logger.warning('%s did not reach the server: %s', label, exc)
            return None
