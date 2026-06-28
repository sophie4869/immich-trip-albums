from trip_albums.planner import build_plan
from trip_albums.escalate import Escalator
from trip_albums.config import load_config
from tests.fixtures import asset
from tests.test_config import base_env


def cfg(**o):
    return load_config(base_env(**o))


def day(n):
    return f"2025-04-{n:02d}T12:00:00Z"


class FakeAdjudicator:
    """Returns canned verdicts and records calls per kind."""

    def __init__(self, boundary_decision="merge"):
        self.boundary_decision = boundary_decision
        self.kinds = []

    def __call__(self, kind, payload):
        self.kinds.append(kind)
        if kind == "resolve_boundary":
            return {"decision": self.boundary_decision, "reason": "llm says so"}
        return {"title": "Nice Trip"}

    def count(self, kind):
        return self.kinds.count(kind)


def esc(adj):
    return Escalator(adjudicator=adj, audit=lambda r: None)


def test_two_separated_trips_need_no_boundary_escalation():
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Rome", country="Italy", taken=day(20)),  # huge gap -> hard split
    ]
    adj = FakeAdjudicator()
    plan = build_plan(assets, cfg(), esc(adj))
    assert len(plan.trips) == 2
    assert adj.count("resolve_boundary") == 0  # hard split, never escalated
    assert adj.count("name_trip") == 2


def test_ambiguous_boundary_merge_yields_one_trip():
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", taken=day(4)),  # 3-day middle-band gap
    ]
    adj = FakeAdjudicator(boundary_decision="merge")
    plan = build_plan(assets, cfg(), esc(adj))
    assert len(plan.trips) == 1
    assert adj.count("resolve_boundary") == 1


def test_ambiguous_boundary_split_yields_two_trips():
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", taken=day(4)),
    ]
    adj = FakeAdjudicator(boundary_decision="split")
    plan = build_plan(assets, cfg(), esc(adj))
    assert len(plan.trips) == 2


def test_review_assets_surfaced():
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="noloc", city=None, lat=None, lon=None, taken=day(2)),
    ]
    plan = build_plan(assets, cfg(), esc(FakeAdjudicator()))
    assert plan.review_asset_ids == ["noloc"]


def test_runs_without_adjudicator_via_fallback():
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", taken=day(4)),
    ]
    plan = build_plan(assets, cfg(), Escalator(adjudicator=None))
    # Fallback: 3-day gap < TRIP_GAP_FALLBACK_DAYS(4) -> merge -> one trip.
    assert len(plan.trips) == 1
    assert plan.trips[0].title.startswith("Trip — ")


def test_title_prefixed_and_sourced():
    assets = [asset(id="a", city="Lisbon", country="Portugal", taken=day(1))]
    plan = build_plan(assets, cfg(), esc(FakeAdjudicator()))
    assert plan.trips[0].title == "Trip — Nice Trip"
    assert plan.trips[0].title_source == "llm"
