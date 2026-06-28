"""The single LLM seam: cache + schema-validation + deterministic fallback + audit.

`Escalator.escalate` is the only place an LLM verdict can enter the pipeline, and
every path has a deterministic fallback, so the whole tool runs with no LLM.
"""


def validate(verdict, schema):
    """Minimal validator: required keys present and enum membership (no jsonschema dep)."""
    if not isinstance(verdict, dict):
        return False
    for key in schema.get("required", []):
        if key not in verdict:
            return False
    for key, allowed in schema.get("enums", {}).items():
        if verdict.get(key) not in allowed:
            return False
    return True


class Escalator:
    def __init__(self, adjudicator=None, audit=None, cache=None):
        self.adjudicator = adjudicator  # callable(kind, payload) -> dict, or None
        self.audit = audit or (lambda record: None)
        self.cache = cache if cache is not None else {}
        self.last = None  # the most recent audit record (lets callers read `applied`)

    def escalate(self, kind, payload, cache_key, schema, fallback_fn):
        # No LLM configured -> deterministic fallback.
        if self.adjudicator is None:
            return self._fallback(kind, cache_key, payload, fallback_fn, reason="no_adjudicator")

        # Cached verdict for this exact key -> reuse (keeps re-runs idempotent).
        if cache_key in self.cache:
            verdict = self.cache[cache_key]
            self._record(kind, cache_key, payload, "cache", verdict, None)
            return verdict

        # Ask the adjudicator; validate; fall back on any failure.
        try:
            verdict = self.adjudicator(kind, payload)
        except Exception as exc:  # noqa: BLE001 - any LLM/transport failure -> fallback
            return self._fallback(kind, cache_key, payload, fallback_fn, reason=f"error:{exc}")

        if not validate(verdict, schema):
            return self._fallback(kind, cache_key, payload, fallback_fn, reason="invalid_verdict")

        self.cache[cache_key] = verdict
        self._record(kind, cache_key, payload, "verdict", verdict, None)
        return verdict

    def _fallback(self, kind, cache_key, payload, fallback_fn, reason):
        verdict = fallback_fn(payload)
        self._record(kind, cache_key, payload, "fallback", verdict, reason)
        return verdict

    def _record(self, kind, cache_key, payload, applied, verdict, reason):
        record = {
            "kind": kind,
            "cache_key": cache_key,
            "payload": payload,
            "applied": applied,
            "verdict": verdict,
            "reason": reason,
        }
        self.last = record
        self.audit(record)
