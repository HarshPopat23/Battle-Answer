from datetime import datetime


def _parse_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamps must be ISO 8601 strings")
    if not value.strip():
        raise ValueError("timestamp must be non-empty")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("timestamp is missing an explicit timezone offset")
    return parsed


def _prepare(bookings):
    for booking in bookings:
        if not isinstance(booking, dict):
            raise ValueError("each booking must be a dictionary")
        for key in ("id", "start", "end"):
            if key not in booking:
                raise ValueError(f"booking is missing {key!r}")
        booking_id = booking["id"]
        if not isinstance(booking_id, str) or not booking_id:
            raise ValueError("booking id must be a nonempty string")


def find_conflicts(bookings):
    """Return sorted, deduplicated conflicting ID pairs for [start, end) bookings."""
    if bookings is None:
        raise ValueError("bookings cannot be None")
    _prepare(bookings)

    seen = set()
    parsed = []
    for booking in bookings:
        booking_id = booking["id"]
        if booking_id in seen:
            raise ValueError(f"duplicate booking id: {booking_id}")
        seen.add(booking_id)
        start = _parse_timestamp(booking["start"])
        end = _parse_timestamp(booking["end"])
        if end <= start:
            raise ValueError(f"end must be after start: {booking_id}")
        parsed.append((booking_id, start, end))

    conflicts = set()
    for i, (id_a, start_a, end_a) in enumerate(parsed):
        for j in range(i + 1, len(parsed)):
            id_b, start_b, end_b = parsed[j]
            if start_a < end_b and start_b < end_a:
                pair = tuple(sorted((id_a, id_b)))
                conflicts.add(pair)
    return sorted(map(list, conflicts))
