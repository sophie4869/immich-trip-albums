import json

import pytest

from trip_albums.immich import ImmichClient, ImmichError


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return self.responses.pop(0)


def client(responses):
    sess = FakeSession(responses)
    return ImmichClient("https://immich.example.com", "secret", session=sess), sess


def test_search_paginates_and_concatenates():
    c, sess = client([
        FakeResponse(200, {"assets": {"items": [{"id": "a1"}], "nextPage": 2}}),
        FakeResponse(200, {"assets": {"items": [{"id": "a2"}], "nextPage": None}}),
    ])
    items = c.search_all_assets()
    assert [a["id"] for a in items] == ["a1", "a2"]
    # Two pages requested with increasing page numbers.
    assert sess.calls[0]["json"]["page"] == 1
    assert sess.calls[1]["json"]["page"] == 2


def test_search_sends_api_key_header_and_excludes_deleted():
    c, sess = client([FakeResponse(200, {"assets": {"items": [], "nextPage": None}})])
    c.search_all_assets()
    assert sess.calls[0]["headers"]["x-api-key"] == "secret"
    assert sess.calls[0]["json"]["withDeleted"] is False
    assert sess.calls[0]["json"]["withExif"] is True


def test_search_passes_date_filters_when_given():
    c, sess = client([FakeResponse(200, {"assets": {"items": [], "nextPage": None}})])
    c.search_all_assets(taken_after="2025-04-01T00:00:00+00:00",
                        taken_before="2025-05-01T00:00:00+00:00")
    body = sess.calls[0]["json"]
    assert body["takenAfter"] == "2025-04-01T00:00:00+00:00"
    assert body["takenBefore"] == "2025-05-01T00:00:00+00:00"


def test_search_omits_date_filters_when_absent():
    c, sess = client([FakeResponse(200, {"assets": {"items": [], "nextPage": None}})])
    c.search_all_assets()
    assert "takenAfter" not in sess.calls[0]["json"]
    assert "takenBefore" not in sess.calls[0]["json"]


def test_non_2xx_raises_named_error():
    c, _ = client([FakeResponse(401, {"error": "unauthorized"})])
    with pytest.raises(ImmichError) as exc:
        c.search_all_assets()
    assert "/api/search/metadata" in str(exc.value)
    assert "401" in str(exc.value)


def test_create_album_posts_body():
    c, sess = client([FakeResponse(201, {"id": "alb1"})])
    out = c.create_album("Trip — Lisbon", "[marker] key=a1", ["a1", "a2"])
    assert out["id"] == "alb1"
    body = sess.calls[0]["json"]
    assert body["albumName"] == "Trip — Lisbon"
    assert body["description"] == "[marker] key=a1"
    assert body["assetIds"] == ["a1", "a2"]
    assert sess.calls[0]["url"].endswith("/api/albums")


def test_rename_album_patches():
    c, sess = client([FakeResponse(200, {"id": "alb1", "albumName": "New"})])
    c.rename_album("alb1", "New")
    assert sess.calls[0]["method"] == "PATCH"
    assert sess.calls[0]["url"].endswith("/api/albums/alb1")
    assert sess.calls[0]["json"]["albumName"] == "New"


def test_add_assets_puts_ids():
    c, sess = client([FakeResponse(200, [])])
    c.add_assets("alb1", ["a3"])
    assert sess.calls[0]["method"] == "PUT"
    assert sess.calls[0]["url"].endswith("/api/albums/alb1/assets")
    assert sess.calls[0]["json"]["ids"] == ["a3"]


