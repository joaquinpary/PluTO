"""Propagating the orbit of the satellite the station is listening to.

Pure with respect to the bus and the network: it takes elements, a station and
an instant and gives back the pass, which is what lets the tests pin a TLE and a
moment and get the same trajectory every time.
"""
from datetime import timedelta

from skyfield.api import EarthSatellite, load, wgs84

# Built once. It carries skyfield's bundled leap-second table and never touches
# the network.
_ts = load.timescale()

RISE, CULMINATION, SET = 0, 1, 2

# How far past the lookahead to keep looking for the set. The lookahead only
# bounds when a pass may start: one that rises at minute 19 of a 20 minute
# window still has to be followed to its end, and no LEO pass lasts this long.
_LONGEST_PASS = timedelta(minutes=30)


def _elevation_deg(satellite, topos, t):
    alt, _, _ = (satellite - topos).at(t).altaz()
    return alt.degrees


def pass_window(satellite, topos, now, min_elevation_deg, lookahead_minutes):
    """(start, end) of the next pass above the threshold, as datetimes, or None.

    find_events only reports what happens inside the interval it is given, so a
    satellite that is already above the threshold has no rise to report for the
    pass in progress. That one is taken from now until its set.
    """
    lookahead = timedelta(minutes=lookahead_minutes)
    t0 = _ts.from_datetime(now)
    t1 = _ts.from_datetime(now + lookahead + _LONGEST_PASS)
    times, events = satellite.find_events(topos, t0, t1, altitude_degrees=min_elevation_deg)

    start = now if _elevation_deg(satellite, topos, t0) >= min_elevation_deg else None
    for t, event in zip(times, events):
        moment = t.utc_datetime()
        if start is None:
            if event == RISE:
                if moment - now > lookahead:
                    return None
                start = moment
        elif event == SET:
            return start, moment

    return None


def next_pass(tle, station, now, min_elevation_deg=10.0, lookahead_minutes=20, sample_seconds=1):
    """The next pass above the threshold, one point every sample_seconds.

    Returns [(datetime, az_deg, el_deg, range_km)] covering only the stretch
    above the threshold, or None when no pass starts within the lookahead.
    """
    satellite = EarthSatellite(tle.line1, tle.line2, tle.name, _ts)
    topos = wgs84.latlon(station['lat'], station['lon'], elevation_m=station['alt'])

    window = pass_window(satellite, topos, now, min_elevation_deg, lookahead_minutes)
    if window is None:
        return None

    start, end = window
    count = int((end - start).total_seconds() // sample_seconds) + 1
    moments = [start + timedelta(seconds=index * sample_seconds) for index in range(count)]

    # One call over an array of instants: skyfield vectorizes, and a ten minute
    # pass is six hundred points.
    alt, az, distance = (satellite - topos).at(_ts.from_datetimes(moments)).altaz()

    # The rise and the set are where the elevation crosses the threshold, so
    # the samples on those instants can come out a hair below it — 9.9999999
    # for a threshold of 10. The dispatcher cuts a trajectory at its first point
    # out of bounds, and one whose very first point is out gets dropped whole,
    # so the edges are trimmed here rather than trusted.
    points = [
        (moment, float(az_deg), float(el_deg), float(range_km))
        for moment, az_deg, el_deg, range_km in zip(moments, az.degrees, alt.degrees, distance.km)
        if el_deg >= min_elevation_deg
    ]
    return points or None


def build_raw_payload(station, points):
    """The message for coordinates/raw: ENU + POLAR, which the engine forwards as is.

    Built by hand rather than with pydantic on purpose. This plugin only ever
    emits this one combination and validates no input, so a copy of models.py
    here would just be a fourth declaration of the valid pairs to keep in sync;
    coord_transform validates the message on the way in.
    """
    return {
        'type': 'ENU',
        'coord_format': 'POLAR',
        'station': {'lat': station['lat'], 'lon': station['lon'], 'alt': station['alt']},
        'coordinates': [
            {'timestamp': moment.isoformat(), 'az': az_deg, 'el': el_deg, 'range': range_km}
            for moment, az_deg, el_deg, range_km in points
        ],
    }
