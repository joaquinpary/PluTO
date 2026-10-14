"""Everything between a plugin's raw trajectory and the board it drives.

A plugin hands its trajectory to submit() and goes on; one worker thread then
transforms it (POST /transform), asks the server for the board and its limits
(GET /api/plugin/rotor) and gives the result to the dispatcher. Both calls can
take a while or need a retry, and neither may run on an MQTT callback, which
would stall the plugin's network loop.

The limits are asked for every trajectory, not once at start: that is when
mqtt_dispatch used to read them, so a change made on the server applies from
the next trajectory, as before.
"""
import logging
import queue
import threading
import time

from .api_client import ApiError, backoff
from .pointing import RotorLimits, parse_polar
from .transform_client import TransformError

logger = logging.getLogger(__name__)


class Antenna:
    def __init__(self, api, transform, dispatcher, max_pending=8, rotor_attempts=5, sleep=time.sleep):
        self.api = api
        self.transform = transform
        self.dispatcher = dispatcher
        self.rotor_attempts = rotor_attempts
        self._sleep = sleep
        # A few trajectories at most: each one supersedes the stretch of time it
        # covers, so a long backlog would only be replayed and overwritten.
        self._queue = queue.Queue(maxsize=max_pending)
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name='pluto-antenna', daemon=True)
        self._thread.start()

    def submit(self, raw):
        """Queue a RawCoordinatesPayload (a dict) to be pointed at. Never blocks."""
        try:
            self._queue.put_nowait(raw)
        except queue.Full:
            logger.error('Antenna queue full, dropping a trajectory of %s points', len(raw.get('coordinates', [])))
            return False
        return True

    def stop(self):
        """Stop the antenna where it is and let the worker go. Called on shutdown."""
        self.dispatcher.stop()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _run(self):
        while True:
            raw = self._queue.get()
            if raw is None:
                return
            try:
                self.process(raw)
            except Exception:
                # One bad trajectory must not take the worker, and with it every
                # later pass, down.
                logger.exception('Could not point at a trajectory')

    def process(self, raw):
        """Transform, fetch the limits and plan one trajectory. Returns whether anything was planned."""
        try:
            polar = self.transform.transform(raw)
        except TransformError as exc:
            logger.error('Trajectory dropped: %s', exc)
            return False

        trajectory = parse_polar(polar)
        if trajectory is None:
            return False

        rotor = self._rotor()
        if rotor is None:
            # Not an error: the board was unbound since the plugin was launched,
            # or the server could not be reached at all.
            logger.info('No board to point, trajectory of %s points dropped', len(trajectory))
            return False

        return self.dispatcher.install(RotorLimits.from_api(rotor), trajectory)

    def _rotor(self):
        for attempt in range(self.rotor_attempts):
            try:
                return self.api.get_rotor()
            except ApiError as exc:
                logger.warning('Could not ask for the board and its limits: %s', exc)
                if attempt + 1 < self.rotor_attempts:
                    self._sleep(backoff(attempt))
        return None
