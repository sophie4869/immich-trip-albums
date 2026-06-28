"""Adjudicators: cache keys, deterministic fallbacks, and the Anthropic call.

The two escalation kinds are ``resolve_boundary`` (merge/split a soft boundary)
and ``name_trip`` (produce an album title). Everything here is pure except
``AnthropicAdjudicator``, which holds an injected ``anthropic.Anthropic`` client.
"""

import json

# Use the most capable model by default; overridable per the claude-api guidance.
LLM_MODEL = "claude-opus-4-8"

# Validation schemas for the escalate() seam (required keys + enum membership).
BOUNDARY_SCHEMA = {"required": ["decision", "reason"], "enums": {"decision": ["merge", "split"]}}
NAME_SCHEMA = {"required": ["title"], "enums": {}}

# JSON schemas for the Anthropic structured-output call (guaranteed-parseable JSON).
_BOUNDARY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["merge", "split"]},
        "reason": {"type": "string"},
    },
    "required": ["decision", "reason"],
    "additionalProperties": False,
}
_NAME_JSON_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}


def boundary_cache_key(boundary, left_country, right_country):
    """Composite key: endpoint identity + decision-relevant fact buckets (spec §8)."""
    gap_bucket = round(boundary.gap_days * 2) / 2  # half-day buckets
    lc = (left_country or "none").lower()
    rc = (right_country or "none").lower()
    dist = boundary.approx_distance_km
    dist_bucket = "na" if dist is None else round(dist / 25)  # 25km buckets
    parts = [boundary.left_id, boundary.right_id, gap_bucket, lc, rc,
             boundary.cause, int(boundary.outlier), dist_bucket]
    return "|".join(str(p) for p in parts)


def make_boundary_fallback(fallback_days):
    """Deterministic boundary verdict: split when gap >= TRIP_GAP_FALLBACK_DAYS."""
    def fallback(payload):
        gap = payload["gap_days"]
        decision = "split" if gap >= fallback_days else "merge"
        return {"decision": decision, "reason": f"fallback: gap {gap:.1f}d vs {fallback_days}d"}
    return fallback


def make_name_fallback():
    """Deterministic title: use the mechanical title precomputed in the payload."""
    def fallback(payload):
        return {"title": payload["fallback_title"]}
    return fallback


_BOUNDARY_SYSTEM = (
    "You decide whether two adjacent clusters of photos belong to the SAME trip "
    "(merge) or DIFFERENT trips (split). Consider the time gap, whether the country "
    "changed, the distance, and the photo counts. A short layover or a single "
    "drive-through shot usually merges into the larger neighbouring trip. Respond "
    "with a decision and a one-sentence reason."
)
_NAME_SYSTEM = (
    "You write a short, human, evocative album title for a trip, given the cities "
    "visited in order, the date range, and the number of photos. Prefer something "
    "natural like 'Lisbon long weekend' or 'Portugal road trip' over a mechanical "
    "city+month label. Keep it under ~6 words. Return only the title text."
)


class AnthropicAdjudicator:
    """Callable ``(kind, payload) -> dict`` backed by the Anthropic Messages API."""

    def __init__(self, client, model=LLM_MODEL):
        self.client = client
        self.model = model

    def __call__(self, kind, payload):
        if kind == "resolve_boundary":
            system, schema = _BOUNDARY_SYSTEM, _BOUNDARY_JSON_SCHEMA
        elif kind == "name_trip":
            system, schema = _NAME_SYSTEM, _NAME_JSON_SCHEMA
        else:
            raise ValueError(f"unknown adjudication kind: {kind}")

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
        )
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)
