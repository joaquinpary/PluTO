"""Reading one field out of a stored payload (RotorState.payload, PluginData.payload)."""


def payload_value(payload, key, kind):
    """payload[key] when it is a `kind`, otherwise None.

    Payloads are whatever a board or a plugin sent, so a missing field or one
    of an unexpected type is an empty cell, never an error. bool is an int in
    Python, and True is not a number of decibels.
    """
    value = payload.get(key) if isinstance(payload, dict) else None
    if isinstance(value, bool) and kind is not bool:
        return None
    return value if isinstance(value, kind) else None
