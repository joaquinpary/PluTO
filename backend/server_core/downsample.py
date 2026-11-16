"""Time series thinning for charts."""


def downsample(rows, time_key, max_points, start=None, end=None, count=None):
    """Keep the last row of each of max_points equal time intervals; gaps stay gaps.

    rows may be an iterator if start, end and count are given; it's walked once.
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
        # All rows in the same instant: keep the last.
        index = min(int((row[time_key] - start) / span * max_points), max_points - 1) if span else 0
        kept[index] = row
    return list(kept.values())
