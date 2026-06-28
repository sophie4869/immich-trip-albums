"""Stable trip identity and deterministic fallback album titles."""

from collections import Counter


def trip_key(assets):
    """Stable identity for a trip: the id of its earliest asset (by taken_at)."""
    earliest = min(assets, key=lambda a: a.taken_at)
    return earliest.id


def _top_cities(assets, limit=2):
    counts = Counter()
    order = []
    for a in assets:
        if a.city:
            if a.city not in counts:
                order.append(a.city)
            counts[a.city] += 1
    # Sort by frequency desc, then by first-seen order for stability.
    ranked = sorted(order, key=lambda c: (-counts[c], order.index(c)))
    return ranked[:limit]


def fallback_title(assets, prefix):
    """Mechanical title: "<prefix><cities>, <Mon Year>" from the earliest asset's date."""
    cities = _top_cities(assets)
    place = " & ".join(cities) if cities else "Unknown area"
    earliest = min(assets, key=lambda a: a.taken_at)
    when = earliest.taken_at.strftime("%b %Y")
    return f"{prefix}{place}, {when}"
