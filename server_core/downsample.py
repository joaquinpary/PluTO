"""Thinning a time series for a chart, which needs a point per pixel and not one per second."""


def downsample(rows, time_key, max_points, start=None, end=None, count=None):
    """At most max_points of rows, which come sorted by time_key, oldest first.

    The span from the first row to the last is cut into max_points equal
    intervals and the last row of each one is kept: a gap in the data stays a
    gap, and every interval shows its most recent value.

    rows may be a list, or an iterator when start, end and count (the first
    time, the last one and how many rows) come along: then it is walked once
    and never more than max_points rows are kept, however long the range.
    """
    if start is None:
        rows = list(rows)
        if not rows:
            return []
        count, start, end = len(rows), rows[0][time_key], rows[-1][time_key]
    if count <= max_points:
        return list(rows)

    span = end - start
    kept = {}
    for row in rows:
        # Every row in the same instant: one interval, the last row.
        index = min(int((row[time_key] - start) / span * max_points), max_points - 1) if span else 0
        kept[index] = row
    return list(kept.values())
