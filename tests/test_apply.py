from trip_albums.apply import apply_plan, MARKER
from trip_albums.config import load_config
from trip_albums.models import Plan, Trip
from tests.fixtures import asset
from tests.test_config import base_env


def cfg(**o):
    return load_config(base_env(**o))


def trip(key, ids, title):
    assets = [asset(id=i, city="Lisbon", country="Portugal") for i in ids]
    # ensure key asset is present
    if key not in ids:
        assets.insert(0, asset(id=key, city="Lisbon", country="Portugal"))
    t = Trip(key=key, assets=assets, title=title)
    return t


class FakeClient:
    def __init__(self, albums=None, tags=None):
        self._albums = albums or []
        self._tags = tags or []
        self.created = []
        self.renamed = []
        self.added = []
        self.created_tags = []
        self.tagged = []

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

    def list_tags(self):
        return self._tags

    def create_tag(self, name):
        self.created_tags.append(name)
        return {"id": "tag-new", "name": name}

    def tag_assets(self, tag_ids, asset_ids):
        self.tagged.append({"tag_ids": tag_ids, "asset_ids": asset_ids})
        return []


def album(album_id, name, key):
    return {"id": album_id, "albumName": name, "description": f"{MARKER}{key}"}


def test_new_trip_creates_album_with_marker():
    plan = Plan(trips=[trip("a", ["a", "b"], "Trip — Lisbon")])
    client = FakeClient(albums=[])
    apply_plan(plan, client, cfg())
    assert len(client.created) == 1
    assert client.created[0]["description"] == f"{MARKER}a"
    assert client.created[0]["name"] == "Trip — Lisbon"


def test_existing_marker_adds_assets_no_create():
    plan = Plan(trips=[trip("a", ["a", "b"], "Trip — Lisbon")])
    client = FakeClient(albums=[album("alb1", "Trip — Lisbon", "a")])
    apply_plan(plan, client, cfg())
    assert client.created == []
    assert client.added[0]["id"] == "alb1"


def test_changed_title_renames_in_place():
    plan = Plan(trips=[trip("a", ["a", "b"], "Trip — Lisbon long weekend")])
    client = FakeClient(albums=[album("alb1", "Trip — Lisbon", "a")])
    apply_plan(plan, client, cfg())
    assert client.created == []
    assert client.renamed[0] == {"id": "alb1", "name": "Trip — Lisbon long weekend"}


def test_tag_reused_when_present():
    plan = Plan(trips=[], review_asset_ids=["r1", "r2"])
    client = FakeClient(tags=[{"id": "t9", "name": "needs-location-review"}])
    apply_plan(plan, client, cfg())
    assert client.created_tags == []
    assert client.tagged[0] == {"tag_ids": ["t9"], "asset_ids": ["r1", "r2"]}


def test_tag_created_when_absent():
    plan = Plan(trips=[], review_asset_ids=["r1"])
    client = FakeClient(tags=[])
    apply_plan(plan, client, cfg())
    assert client.created_tags == ["needs-location-review"]
    assert client.tagged[0]["tag_ids"] == ["tag-new"]


def test_no_tagging_when_no_review_assets():
    plan = Plan(trips=[], review_asset_ids=[])
    client = FakeClient(tags=[])
    apply_plan(plan, client, cfg())
    assert client.tagged == []
    assert client.created_tags == []


def test_earlier_import_overlap_is_warned_not_duplicated():
    # Existing album keyed on "a"; the new trip's key shifted to "z" but it
    # still contains asset "a" -> overlap. Report, don't create a duplicate.
    plan = Plan(trips=[trip("z", ["z", "a", "b"], "Trip — Lisbon")])
    client = FakeClient(albums=[album("alb1", "Trip — Lisbon", "a")])
    result = apply_plan(plan, client, cfg())
    assert client.created == []
    assert len(result.warnings) == 1
