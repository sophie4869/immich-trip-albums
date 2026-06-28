from trip_albums.adjudicate import (
    boundary_cache_key,
    make_boundary_fallback,
    make_name_fallback,
    BOUNDARY_SCHEMA,
    NAME_SCHEMA,
    AnthropicAdjudicator,
)
from trip_albums.models import Boundary


def boundary(left_id="a", right_id="b", gap_days=3.0, cause="middle_band",
             outlier=False, dist=120.0):
    return Boundary(index=0, gap_days=gap_days, cause=cause, hard=False,
                    outlier=outlier, approx_distance_km=dist,
                    left_id=left_id, right_id=right_id)


# --- composite cache key ----------------------------------------------------

def test_cache_key_stable_for_same_inputs():
    b = boundary()
    assert boundary_cache_key(b, "Portugal", "Portugal") == boundary_cache_key(b, "Portugal", "Portugal")


def test_cache_key_changes_with_gap_bucket():
    k1 = boundary_cache_key(boundary(gap_days=3.0), "PT", "PT")
    k2 = boundary_cache_key(boundary(gap_days=5.0), "PT", "PT")
    assert k1 != k2


def test_cache_key_distinct_for_different_endpoints_same_facts():
    # Same fact buckets, different endpoint ids -> different key (no collision).
    k1 = boundary_cache_key(boundary(left_id="a", right_id="b"), "PT", "ES")
    k2 = boundary_cache_key(boundary(left_id="c", right_id="d"), "PT", "ES")
    assert k1 != k2


def test_cache_key_handles_none_country_and_distance():
    b = boundary(dist=None)
    key = boundary_cache_key(b, None, None)
    assert "none" in key and "na" in key


# --- fallbacks --------------------------------------------------------------

def test_boundary_fallback_splits_above_threshold():
    fb = make_boundary_fallback(4.0)
    assert fb({"gap_days": 5.0})["decision"] == "split"


def test_boundary_fallback_merges_below_threshold():
    fb = make_boundary_fallback(4.0)
    assert fb({"gap_days": 2.0})["decision"] == "merge"


def test_name_fallback_uses_payload_fallback_title():
    fb = make_name_fallback()
    assert fb({"fallback_title": "Trip — Lisbon, Apr 2025"})["title"] == "Trip — Lisbon, Apr 2025"


# --- schemas ----------------------------------------------------------------

def test_schema_shapes():
    assert "decision" in BOUNDARY_SCHEMA["required"]
    assert BOUNDARY_SCHEMA["enums"]["decision"] == ["merge", "split"]
    assert "title" in NAME_SCHEMA["required"]


# --- AnthropicAdjudicator with a stubbed client (no network) ----------------

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _StubMessages:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self._text)


class _StubClient:
    def __init__(self, text):
        self.messages = _StubMessages(text)


def test_adjudicator_parses_boundary_json():
    client = _StubClient('{"decision": "merge", "reason": "same trip"}')
    adj = AnthropicAdjudicator(client)
    out = adj("resolve_boundary", {"gap_days": 2.0, "left": {}, "right": {}})
    assert out == {"decision": "merge", "reason": "same trip"}
    assert client.messages.calls[0]["model"]  # a model was passed


def test_adjudicator_parses_name_json():
    client = _StubClient('{"title": "Portugal road trip"}')
    adj = AnthropicAdjudicator(client)
    out = adj("name_trip", {"cities_in_order": ["Lisbon"], "fallback_title": "x"})
    assert out["title"] == "Portugal road trip"


def test_adjudicator_rejects_unknown_kind():
    adj = AnthropicAdjudicator(_StubClient("{}"))
    try:
        adj("bogus", {})
        assert False, "expected ValueError"
    except ValueError:
        pass
