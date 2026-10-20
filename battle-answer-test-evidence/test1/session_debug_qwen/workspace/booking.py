"""Booking conflict detection."""

from datetime import datetime, timezone


def _parse_timestamp(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty ISO 8601 timestamp string")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"malformed timestamp in {field}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError(f"missing timezone in {field}: {value!r}")
    # Normalize to UTC so comparisons are across absolute instants.
    return parsed.astimezone(timezone.utc)


def _validate_booking(booking, seen_ids):
    if not isinstance(booking, dict):
        raise ValueError("each booking must be a dict")
    booking_id = booking.get("id")
    if not isinstance(booking_id, str) or not booking_id:
        raise ValueError("booking id must be a nonempty string")
    if booking_id in seen_ids:
        raise ValueError(f"duplicate booking id: {booking_id!r}")
    seen_ids.add(booking_id)
    if "start" not in booking or "end" not in booking:
        raise ValueError(f"booking {booking_id!r} missing start or end")
    start = _parse_timestamp(booking["start"], "start")
    end = _parse_timestamp(booking["end"], "end")
    if end <= start:
        raise ValueError(
            f"booking {booking_id!r} has end <= start: {end.isoformat()} <= {start.isoformat()}"
        )
    return booking_id, start, end


def find_conflicts(bookings):
    """Return sorted, de-duplicated conflicting booking ID pairs.

    Intervals are half-open [start, end). Equal endpoints do not conflict.
    A pair (X, Y) is reported once, with the two IDs sorted and the list
    sorted lexicographically. Input is not mutated.
    """
    if bookings is None:
        raise ValueError("bookings must be a list, not None")
    if not isinstance(bookings, (list, tuple)):
        raise ValueError("bookings must be a list of booking dicts")

    normalized = []
    seen_ids = set()
    for booking in bookings:
        normalized.append(_validate_booking(booking, seen_ids))

    n = len(normalized)
    pairs = []
    for i in range(n):
        id_i, start_i, end_i = normalized[i]
        for j in range(i + 1, n):
            id_j, start_j, end_j = normalized[j]
            # Half-open overlap: max(starts) < min(ends).
            if max(start_i, start_j) < min(end_i, end_j):
                pair = tuple(sorted((id_i, id_j)))
                if pair not in pairs:
                    pairs.append(pair)

    pairs.sort()
    return pairs
