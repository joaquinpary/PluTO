"""POST /transform on coord_transform (docs/contracts/transform-api.md).

Called from the antenna's worker thread, never from an MQTT callback, so it may
block and retry: a pass is computed minutes before it starts, and a few seconds
spent waiting for coord_transform to come back change nothing.
"""
import json
import logging
import time
import urllib.error
import urllib.request

from .api_client import backoff

logger = logging.getLogger(__name__)


class TransformError(Exception):
    pass


class TransformClient:
    def __init__(self, base_url, timeout=30.0, attempts=5,
                 urlopen=urllib.request.urlopen, sleep=time.sleep):
        self.url = base_url.rstrip('/') + '/transform'
        self.timeout = timeout
        self.attempts = attempts
        self._urlopen = urlopen
        self._sleep = sleep

    def transform(self, raw):
        """A RawCoordinatesPayload (dict) -> the PolarCoordinatesPayload (dict). Raises TransformError."""
        body = json.dumps(raw).encode('utf-8')
        for attempt in range(self.attempts):
            request = urllib.request.Request(
                self.url, data=body, method='POST', headers={'Content-Type': 'application/json'},
            )
            try:
                with self._urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read(1000).decode('utf-8', errors='replace')
                if exc.code < 500:
                    # The trajectory itself is wrong; asking again gets the same answer.
                    raise TransformError(f'coord_transform rejected the trajectory ({exc.code}): {detail}') from None
                logger.warning('coord_transform answered %s: %s', exc.code, detail)
            except (urllib.error.URLError, OSError) as exc:
                logger.warning('coord_transform did not answer: %s', exc)

            if attempt + 1 < self.attempts:
                self._sleep(backoff(attempt))

        raise TransformError(f'coord_transform did not answer after {self.attempts} attempts')
