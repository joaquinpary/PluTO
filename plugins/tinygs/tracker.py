"""Deciding when a new pass is worth computing, and computing it off the bus.

The tracking message arrives retained, again on every reconnect of the station,
and every 15 minutes as a heartbeat even when nothing changed. Acting on each
one would mean asking CelesTrak and republishing the same pass over and over.
And the work cannot run on paho's network thread: a slow download there would
also stall the rx republishing this plugin already owes the ingester.
"""
import json
import logging
import threading
from datetime import datetime, timezone

from trajectory import build_raw_payload, next_pass

logger = logging.getLogger(__name__)

# What the station reports before the TinyGS server has assigned it anything:
# the name is a placeholder and the NORAD is the compiled-in default
# (FossaSat-3), not a satellite anybody asked to follow.
UNASSIGNED = 'Waiting'


def utc_now():
    return datetime.now(timezone.utc)


def assigned_norad(document):
    """The catalog number a tracking message asks to follow, or None."""
    if not isinstance(document, dict) or document.get('satellite') == UNASSIGNED:
        return None

    norad = document.get('NORAD')
    # bool is an int in Python, and True is not a catalog number.
    if isinstance(norad, bool) or not isinstance(norad, int) or norad <= 0:
        return None

    return norad


class Tracker:
    """Turns the satellite the station is following into a pass on coordinates/raw."""

    def __init__(self, station, cache, publish, topic, min_elevation_deg=10.0,
                 lookahead_minutes=20, sample_seconds=1, clock=utc_now, compute=next_pass):
        self.station = station
        self.cache = cache
        self.topic = topic
        self.min_elevation_deg = min_elevation_deg
        self.lookahead_minutes = lookahead_minutes
        self.sample_seconds = sample_seconds
        self._publish = publish
        self._clock = clock
        self._compute = compute

        self.last_norad = None
        self.last_pass_end = None

        # A one-slot mailbox: only the latest satellite matters, so several
        # tracking messages in a row never queue repeated work.
        self._lock = threading.Lock()
        self._pending = None
        self._wake = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name='tinygs-tracker', daemon=True).start()

    def on_tracking(self, document):
        """Queue a recompute if this tracking message calls for one."""
        norad = assigned_norad(document)
        if norad is None:
            logger.info('The station has no satellite assigned yet, nothing to track')
            return

        if not self.needs_recompute(norad):
            logger.debug('Still following %s and its pass is not over, nothing to do', norad)
            return

        with self._lock:
            self._pending = norad
        self._wake.set()

    def needs_recompute(self, norad):
        if norad != self.last_norad:
            return True
        # Same satellite, but the pass we published is over: the 15 minute
        # heartbeat is the tick that catches its next one.
        return self.last_pass_end is None or self._clock() >= self.last_pass_end

    def take_pending(self):
        with self._lock:
            norad, self._pending = self._pending, None
        return norad

    def process(self, norad):
        """Publish the next pass for norad, unless one is already out. Returns whether it did."""
        # Checked again here and not only when queued: the retained message and
        # the one the station sends on reconnect can land together, before the
        # first pass has been recorded.
        if not self.needs_recompute(norad):
            return False

        tle = self.cache.get(norad)
        points = self._compute(
            tle, self.station, self._clock(),
            min_elevation_deg=self.min_elevation_deg,
            lookahead_minutes=self.lookahead_minutes,
            sample_seconds=self.sample_seconds,
        )
        if not points:
            # Nothing is recorded, so the next tracking message tries again.
            logger.info('No pass of %s (%s) starts within %s minutes', tle.name, norad, self.lookahead_minutes)
            return False

        self._publish(self.topic, json.dumps(build_raw_payload(self.station, points)))
        self.last_norad = norad
        self.last_pass_end = points[-1][0]
        logger.info(
            'Published a pass of %s (%s): %s points from %s to %s',
            tle.name, norad, len(points), points[0][0].isoformat(), points[-1][0].isoformat(),
        )
        return True

    def _run(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            norad = self.take_pending()
            if norad is None:
                continue
            try:
                self.process(norad)
            except Exception:
                # CelesTrak down, a broken TLE: log it and wait for the next
                # tracking message rather than lose the thread.
                logger.exception('Could not compute a pass for %s', norad)
