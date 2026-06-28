"""Human-readable dry-run plan rendering."""


def _fmt_date(dt):
    return dt.strftime("%Y-%m-%d") if dt else "?"


def render_plan(plan):
    lines = []
    lines.append(f"Trips ({len(plan.trips)})  |  home photos skipped: {plan.home_count}  "
                 f"|  to review (tagged): {len(plan.review_asset_ids)}")
    lines.append("")

    for t in plan.trips:
        src = {"llm": "LLM", "cache": "LLM(cached)", "fallback": "auto"}.get(t.title_source, t.title_source)
        lines.append(f"  • {t.title}  [{src}]")
        lines.append(f"      {_fmt_date(t.start)} → {_fmt_date(t.end)}   ({len(t.assets)} items)")

    if plan.decisions:
        lines.append("")
        lines.append("Ambiguous boundaries adjudicated:")
        for d in plan.decisions:
            left = ", ".join(d["left_cities"]) or "?"
            right = ", ".join(d["right_cities"]) or "?"
            lines.append(
                f"  • {left} | {right}  gap {d['gap_days']:.1f}d ({d['cause']}) "
                f"→ {d['decision']} [{d['source']}] — {d['reason']}"
            )

    if plan.warnings:
        lines.append("")
        lines.append("Warnings (need manual reconciliation):")
        for w in plan.warnings:
            lines.append(f"  ! {w}")

    return "\n".join(lines)
