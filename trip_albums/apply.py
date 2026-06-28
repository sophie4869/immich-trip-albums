"""Idempotent application of a Plan to Immich: albums + review tag (spec §9)."""

from dataclasses import dataclass, field

MARKER = "[immich-trip-albummer] key="


@dataclass
class ApplyResult:
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    renamed: list = field(default_factory=list)
    tagged_count: int = 0
    warnings: list = field(default_factory=list)


def _parse_marker(description):
    """Extract the trip_key from an album description marker, or None."""
    if not description or MARKER not in description:
        return None
    after = description.split(MARKER, 1)[1]
    return after.split()[0] if after.split() else after.strip() or None


def _index_albums(client):
    index = {}
    for album in client.list_albums():
        key = _parse_marker(album.get("description"))
        if key:
            index[key] = album
    return index


def apply_plan(plan, client, config):
    result = ApplyResult()
    existing = _index_albums(client)

    for trip in plan.trips:
        if trip.key in existing:
            album = existing[trip.key]
            client.add_assets(album["id"], trip.asset_ids)
            result.updated.append(album["id"])
            if album.get("albumName") != trip.title:
                client.rename_album(album["id"], trip.title)
                result.renamed.append(album["id"])
            continue

        # Not matched by key. If an existing tool-made album's key is among this
        # trip's assets, the trip identity shifted (e.g. an earlier import) and
        # creating would duplicate — report instead of acting (spec §9 limits).
        trip_asset_ids = set(trip.asset_ids)
        overlap = [k for k in existing if k in trip_asset_ids]
        if overlap:
            result.warnings.append(
                f"Trip {trip.key!r} ({trip.title!r}) overlaps existing album(s) "
                f"keyed {overlap}; skipped to avoid a duplicate — reconcile manually."
            )
            continue

        client.create_album(trip.title, f"{MARKER}{trip.key}", trip.asset_ids)
        result.created.append(trip.title)

    _apply_tag(plan, client, config, result)
    return result


def _apply_tag(plan, client, config, result):
    if not plan.review_asset_ids:
        return
    tag_id = None
    for tag in client.list_tags():
        if (tag.get("name") or "").lower() == config.review_tag.lower():
            tag_id = tag["id"]
            break
    if tag_id is None:
        tag_id = client.create_tag(config.review_tag)["id"]
    client.tag_assets([tag_id], plan.review_asset_ids)
    result.tagged_count = len(plan.review_asset_ids)
