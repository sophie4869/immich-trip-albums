"""Command-line entry point: wire config + client + LLM seam, dry-run by default."""

import argparse
import json
import os
import sys

from .apply import apply_plan
from .config import ConfigError, load_config
from .escalate import Escalator
from .immich import ImmichClient, ImmichError
from .models import Asset
from .planner import build_plan
from .render import render_plan

AUDIT_PATH = "escalations.jsonl"


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


def make_immich_client(config):
    return ImmichClient(config.immich_url, config.immich_api_key)


def make_adjudicator(config):
    if not config.llm_enabled:
        return None
    import anthropic  # imported lazily so --no-llm runs need no SDK call path
    from .adjudicate import AnthropicAdjudicator
    return AnthropicAdjudicator(anthropic.Anthropic(api_key=config.anthropic_api_key))


def _make_audit(path):
    handle = open(path, "a")

    def audit(record):
        handle.write(json.dumps(record, default=str) + "\n")
        handle.flush()

    return audit, handle


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="trip-albums",
        description="Cluster away-from-home Immich photos/videos into trip albums.",
    )
    parser.add_argument("--apply", action="store_true", help="Perform writes (default: dry run).")
    parser.add_argument("--no-llm", action="store_true", help="Force deterministic-only (no LLM).")
    parser.add_argument("--env", metavar="PATH", help="Path to a .env file to merge over the environment.")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if args.env:
        env.update(_load_env_file(args.env))

    try:
        config = load_config(env, no_llm=args.no_llm)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    client = make_immich_client(config)
    adjudicator = make_adjudicator(config)
    audit, handle = _make_audit(AUDIT_PATH)
    try:
        escalator = Escalator(adjudicator=adjudicator, audit=audit)

        try:
            raw = client.search_all_assets()
        except ImmichError as exc:
            print(f"Immich error: {exc}", file=sys.stderr)
            return 1
        assets = [Asset.from_api(a) for a in raw]

        plan = build_plan(assets, config, escalator)
        print(render_plan(plan))

        if args.apply:
            result = apply_plan(plan, client, config)
            print("")
            print(f"APPLIED: {len(result.created)} created, {len(result.updated)} updated, "
                  f"{len(result.renamed)} renamed, {result.tagged_count} tagged.")
            for w in result.warnings:
                print(f"  ! {w}")
        else:
            print("")
            print("DRY RUN — nothing was changed. Re-run with --apply to create albums and tags.")
        return 0
    finally:
        handle.close()


if __name__ == "__main__":
    sys.exit(main())
