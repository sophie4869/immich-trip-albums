"""Command-line entry point: wire config + client, dry-run by default."""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from .apply import apply_plan, _index_albums
from .config import ConfigError, load_config
from .immich import ImmichClient, ImmichError
from .models import Asset
from .planner import build_plan
from .render import render_plan


def _load_env_file(path):
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def _parse_day(value, end_of_day):
    """Parse YYYY-MM-DD into a UTC datetime at the start or end of that day."""
    day = datetime.strptime(value, "%Y-%m-%d").date()
    t = datetime.max.time() if end_of_day else datetime.min.time()
    return datetime.combine(day, t, tzinfo=timezone.utc)


def _parse_window(since, until, gap_max_days):
    """Return (window, fetch_after_iso, fetch_before_iso).

    `window` is the (since, until) pair used to keep only in-window trips. The
    fetch range is widened by `gap_max_days` on each side so trips straddling a
    window edge still cluster correctly. Returns (None, None, None) when unset.
    """
    if not since and not until:
        return None, None, None
    since_dt = _parse_day(since, end_of_day=False) if since else None
    until_dt = _parse_day(until, end_of_day=True) if until else None
    buffer = timedelta(days=gap_max_days)
    fetch_after = (since_dt - buffer).isoformat() if since_dt else None
    fetch_before = (until_dt + buffer).isoformat() if until_dt else None
    return (since_dt, until_dt), fetch_after, fetch_before


def make_immich_client(config):
    return ImmichClient(config.immich_url, config.immich_api_key)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="trip-albums",
        description="Cluster away-from-home Immich photos/videos into trip albums.",
    )
    parser.add_argument("--apply", action="store_true", help="Perform writes (default: dry run).")
    parser.add_argument("--env", metavar="PATH", help="Path to a .env file to merge over the environment.")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="Only album trips with photos taken on/after this date.")
    parser.add_argument("--until", metavar="YYYY-MM-DD", help="Only album trips with photos taken on/before this date.")
    args = parser.parse_args(argv)

    env_path = args.env or (".env" if os.path.isfile(".env") else None)
    if env_path:
        env = _load_env_file(env_path)
        env.update(os.environ)  # real env vars override .env defaults
    else:
        env = dict(os.environ)

    try:
        config = load_config(env)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        window, fetch_after, fetch_before = _parse_window(args.since, args.until, config.gap_max_days)
    except ValueError:
        print("Invalid --since/--until: use YYYY-MM-DD.", file=sys.stderr)
        return 2

    client = make_immich_client(config)

    try:
        raw = client.search_all_assets(taken_after=fetch_after, taken_before=fetch_before)
    except ImmichError as exc:
        print(f"Immich error: {exc}", file=sys.stderr)
        return 1
    assets = [Asset.from_api(a) for a in raw]

    existing_albums = _index_albums(client)
    existing_keys = set(existing_albums.keys())

    plan = build_plan(assets, config, window=window, existing_keys=existing_keys)
    if window is not None:
        scope = f"{args.since or '…'} → {args.until or '…'}"
        print(f"(scoped to {scope}; a {config.gap_max_days:g}-day buffer was fetched for correct edge clustering)")
    print(render_plan(plan))

    if args.apply:
        result = apply_plan(plan, client)
        print("")
        print(f"APPLIED: {len(result.created)} created, {len(result.updated)} updated, "
              f"{len(result.renamed)} renamed.")
        for w in result.warnings:
            print(f"  ! {w}")
    else:
        print("")
        print("DRY RUN — nothing was changed. Re-run with --apply to create albums.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
