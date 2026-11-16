"""Reading fields out of stored payloads."""


def payload_value(payload, key, kind):
    """payload[key] if it is a `kind` (bools aren't numbers), else None."""
    value = payload.get(key) if isinstance(payload, dict) else None
    if isinstance(value, bool) and kind is not bool:
        return None
    return value if isinstance(value, kind) else None
