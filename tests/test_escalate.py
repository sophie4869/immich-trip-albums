from trip_albums.escalate import Escalator, validate


SCHEMA = {"required": ["decision", "reason"], "enums": {"decision": ["merge", "split"]}}


def fallback(payload):
    return {"decision": "split", "reason": "fallback"}


class FakeAdjudicator:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def __call__(self, kind, payload):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make(adjudicator):
    audit_log = []
    esc = Escalator(adjudicator=adjudicator, audit=audit_log.append)
    return esc, audit_log


# --- validate ---------------------------------------------------------------

def test_validate_accepts_good_verdict():
    assert validate({"decision": "merge", "reason": "x"}, SCHEMA) is True


def test_validate_rejects_missing_key():
    assert validate({"decision": "merge"}, SCHEMA) is False


def test_validate_rejects_bad_enum():
    assert validate({"decision": "maybe", "reason": "x"}, SCHEMA) is False


# --- escalate ---------------------------------------------------------------

def test_valid_verdict_is_adopted_and_cached():
    adj = FakeAdjudicator({"decision": "merge", "reason": "same trip"})
    esc, log = make(adj)
    v1 = esc.escalate("resolve_boundary", {"x": 1}, "k1", SCHEMA, fallback)
    v2 = esc.escalate("resolve_boundary", {"x": 1}, "k1", SCHEMA, fallback)
    assert v1 == {"decision": "merge", "reason": "same trip"}
    assert v2 == v1
    assert adj.calls == 1  # second call served from cache
    assert [r["applied"] for r in log] == ["verdict", "cache"]


def test_invalid_verdict_falls_back():
    adj = FakeAdjudicator({"decision": "nope", "reason": "x"})
    esc, log = make(adj)
    v = esc.escalate("resolve_boundary", {}, "k1", SCHEMA, fallback)
    assert v == {"decision": "split", "reason": "fallback"}
    assert log[-1]["applied"] == "fallback"


def test_adjudicator_exception_falls_back():
    adj = FakeAdjudicator(RuntimeError("boom"))
    esc, log = make(adj)
    v = esc.escalate("resolve_boundary", {}, "k1", SCHEMA, fallback)
    assert v["reason"] == "fallback"
    assert log[-1]["applied"] == "fallback"


def test_no_adjudicator_always_falls_back_without_calling():
    esc, log = make(None)
    v = esc.escalate("resolve_boundary", {}, "k1", SCHEMA, fallback)
    assert v == {"decision": "split", "reason": "fallback"}
    assert log[-1]["applied"] == "fallback"


def test_distinct_keys_do_not_share_results():
    adj = FakeAdjudicator({"decision": "merge", "reason": "x"})
    esc, _ = make(adj)
    esc.escalate("resolve_boundary", {"a": 1}, "k1", SCHEMA, fallback)
    esc.escalate("resolve_boundary", {"a": 2}, "k2", SCHEMA, fallback)
    assert adj.calls == 2  # different keys -> two calls, no collision
