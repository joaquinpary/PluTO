"""Downloading and caching the orbital elements of a satellite.

CelesTrak is the source — it needs no key — and it is the only place in the
project that reaches outside the host, so the network call is one thin function
and everything around it is pure: the parser and the cache are tested without
opening a socket.
"""
import logging
import time
import urllib.request
from collections import namedtuple

logger = logging.getLogger(__name__)

CELESTRAK_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=TLE'

# CelesTrak asks callers to identify themselves, and urllib's default
# "Python-urllib/3.x" is exactly the kind of anonymous client it throttles.
USER_AGENT = 'PluTO/1.0 (satellite tracker; github.com/joaquinpary/PluTO)'

# What CelesTrak answers for a catalog number it does not know. It comes with a
# 200, not a 404, so it has to be recognized by its text.
_NO_DATA = 'no gp data found'

Tle = namedtuple('Tle', 'name line1 line2')


def download(url, timeout=10.0):
    """The one call that leaves the host."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode('utf-8')


def parse_tle_response(text):
    """The three lines CelesTrak returns -> Tle. Raises ValueError if it is not one."""
    if _NO_DATA in text.lower():
        raise ValueError('CelesTrak has no elements for that catalog number')

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 3:
        raise ValueError(f'expected a name and two element lines, got {len(lines)} lines')

    name, line1, line2 = lines
    if not line1.startswith('1 ') or not line2.startswith('2 '):
        raise ValueError('the element lines must start with "1 " and "2 "')

    return Tle(name, line1, line2)


def fetch_from_celestrak(norad):
    return parse_tle_response(download(CELESTRAK_URL.format(norad=norad)))


class TleCache:
    """Keeps a TLE per catalog number for a while.

    A TLE stays good for days while a pass is recomputed every few minutes at
    most, so going to CelesTrak each time would be rude for no gain. It lives in
    memory only: plugins never touch the database, and losing it on a restart
    costs a single download.
    """

    def __init__(self, ttl_seconds, fetch=fetch_from_celestrak, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self._fetch = fetch
        # Monotonic, so a clock step on the host never makes a TLE look fresh.
        self._clock = clock
        self._entries = {}

    def get(self, norad):
        now = self._clock()
        cached = self._entries.get(norad)
        if cached is not None and now - cached[1] < self.ttl_seconds:
            return cached[0]

        try:
            tle = self._fetch(norad)
        except Exception:
            if cached is None:
                raise
            # Elements a few hours past their TTL still put the antenna within a
            # fraction of a degree; failing the whole pass because CelesTrak is
            # unreachable would be far worse.
            logger.warning('Could not refresh the elements for %s, using the cached ones', norad, exc_info=True)
            return cached[0]

        self._entries[norad] = (tle, now)
        logger.info('Fetched the elements for %s (%s)', norad, tle.name)
        return tle
