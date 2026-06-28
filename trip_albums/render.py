"""Human-readable dry-run plan rendering."""


def _fmt_date(dt):
    return dt.strftime("%Y-%m-%d") if dt else "?"


def render_plan(plan):
    lines = []
    summary = (f"Trips ({len(plan.trips)})  |  home photos skipped: {plan.home_count}")
    if plan.skip_count:
        summary += f"  |  no-location photos skipped: {plan.skip_count}"
    if plan.review_count:
        summary += f"  |  no-location photos near a trip: {plan.review_count}"
    lines.append(summary)
    lines.append("")

    for t in plan.trips:
        lines.append(f"  • {t.title}")
        lines.append(f"      {_fmt_date(t.start)} → {_fmt_date(t.end)}   ({len(t.assets)} items)")

    if plan.existing_trips:
        lines.append("")
        lines.append(f"Already albumed ({len(plan.existing_trips)}, skipped):")
        for t in plan.existing_trips:
            lines.append(f"  • {t.title}")
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
