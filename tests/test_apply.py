from trip_albums.apply import apply_plan, MARKER
from trip_albums.models import Plan, Trip
from tests.fixtures import asset


def trip(key, ids, title):
    assets = [asset(id=i, city="Lisbon", country="Portugal") for i in ids]
    # ensure key asset is present
    if key not in ids:
        assets.insert(0, asset(id=key, city="Lisbon", country="Portugal"))
    t = Trip(key=key, assets=assets, title=title)
    return t


class FakeClient:
    def __init__(self, albums=None):
        self._albums = albums or []
        self.created = []
        self.renamed = []
        self.added = []

    def list_albums(self):
        return self._albums

    def create_album(self, name, description, asset_ids):
        self.created.append({"name": name, "description": description, "ids": asset_ids})
        return {"id": "new-album"}

    def rename_album(self, album_id, name):
        self.renamed.append({"id": album_id, "name": name})
        return {}

    def add_assets(self, album_id, asset_ids):
        self.added.append({"id": album_id, "ids": asset_ids})
        return []


def album(album_id, name, key):
    return {"id": album_id, "albumName": name, "description": f"{MARKER}{key}"}


def test_new_trip_creates_album_with_marker():
    plan = Plan(trips=[trip("a", ["a", "b"], "Trip — Lisbon")])
    client = FakeClient(albums=[])
    apply_plan(plan, client)
    assert len(client.created) == 1
    assert client.created[0]["description"] == f"{MARKER}a"
    assert client.created[0]["name"] == "Trip — Lisbon"


def test_existing_marker_adds_assets_no_create():
    plan = Plan(trips=[trip("a", ["a", "b"], "Trip — Lisbon")])
    client = FakeClient(albums=[album("alb1", "Trip — Lisbon", "a")])
    apply_plan(plan, client)
    assert client.created == []
    assert client.added[0]["id"] == "alb1"


def test_changed_title_renames_in_place():
    plan = Plan(trips=[trip("a", ["a", "b"], "Trip — Lisbon long weekend")])
    client = FakeClient(albums=[album("alb1", "Trip — Lisbon", "a")])
    apply_plan(plan, client)
    assert client.created == []
    assert client.renamed[0] == {"id": "alb1", "name": "Trip — Lisbon long weekend"}


def test_no_action_when_no_trips():
    plan = Plan(trips=[])
    client = FakeClient()
    result = apply_plan(plan, client)
    assert client.created == []
    assert result.warnings == []


def test_earlier_import_overlap_is_warned_not_duplicated():
    # Existing album keyed on "a"; the new trip's key shifted to "z" but it
    # still contains asset "a" -> overlap. Report, don't create a duplicate.
    plan = Plan(trips=[trip("z", ["z", "a", "b"], "Trip — Lisbon")])
    client = FakeClient(albums=[album("alb1", "Trip — Lisbon", "a")])
    result = apply_plan(plan, client)
    assert client.created == []
    assert len(result.warnings) == 1
