import trip_albums.cli as cli
from trip_albums.render import render_plan
from trip_albums.models import Plan, Trip
from tests.fixtures import asset, api_asset
from tests.test_config import base_env


def test_render_includes_title_dates_and_review_count():
    t = Trip(key="a", assets=[asset(id="a", city="Lisbon", taken="2025-04-01T10:00:00Z")],
             title="Trip — Lisbon")
    plan = Plan(trips=[t], review_asset_ids=["r1", "r2"], home_count=5)
    text = render_plan(plan)
    assert "Trip — Lisbon" in text
    assert "2" in text  # review count
    assert "1 trip" in text or "Trips (1)" in text


def test_render_shows_boundary_decisions_and_warnings():
    plan = Plan(
        trips=[],
        decisions=[{"left_cities": ["Lisbon"], "right_cities": ["Porto"], "gap_days": 3.0,
                    "cause": "middle_band", "decision": "merge", "reason": "same trip",
                    "source": "llm"}],
        warnings=["something to reconcile"],
    )
    text = render_plan(plan)
    assert "merge" in text
    assert "something to reconcile" in text


class FakeImmich:
    def __init__(self):
        self.applied = False

    def search_all_assets(self):
        return [
            api_asset(id="a", city="Lisbon", country="Portugal", taken="2025-04-01T10:00:00Z"),
            api_asset(id="b", city="Rome", country="Italy", taken="2025-04-20T10:00:00Z"),
        ]


def test_main_dry_run_no_llm(monkeypatch, capsys):
    for k, v in base_env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(cli, "make_immich_client", lambda config: FakeImmich())

    rc = cli.main(["--no-llm"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN" in out.upper()
    assert "Trip — " in out  # at least one trip rendered


def test_main_apply_calls_apply(monkeypatch, capsys):
    for k, v in base_env().items():
        monkeypatch.setenv(k, v)

    fake = FakeImmich()
    monkeypatch.setattr(cli, "make_immich_client", lambda config: fake)
    captured = {}

    def fake_apply(plan, client, config):
        captured["applied"] = True
        from trip_albums.apply import ApplyResult
        return ApplyResult(created=["Trip — X"])

    monkeypatch.setattr(cli, "apply_plan", fake_apply)
    rc = cli.main(["--no-llm", "--apply"])
    assert rc == 0
    assert captured.get("applied") is True
