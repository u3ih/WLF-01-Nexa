"""Deterministic answers.

Used when no model is reachable, and as the final fallback if a model reply
keeps breaking a hard rule. Every sentence here is built from engine output, so
it can never invent a figure.

No wording is written here. Each line is a `summary.*` key in
`app/i18n/{vi,en}.json`, filled with engine numbers, so VI and EN can never
drift apart and a third language is a catalog file, not a code change. Lines
made only of data and punctuation — a date, an amount, a reference — stay as
f-strings: they read the same in every language.
"""

from __future__ import annotations

from typing import Any

from ..engine.models import fmt_display
from ..engine.render import t

BULLET = "• "


def _finding_lines(findings: list[dict[str, Any]], lang: str,
                   limit: int = 6) -> list[str]:
    lines = []
    for item in findings[:limit]:
        lines.append(f"{BULLET}[{item['label_text']}] {item['title']}")
        lines.append(f"  {item['detail']}")
        if item.get("dispute", {}).get("text"):
            lines.append(f"  {item['dispute']['text']}")
        sources = ", ".join(f"{s['kind_text']}:{s['ref']}"
                            for s in item.get("sources", []))
        if sources:
            lines.append("  " + t(lang, "common.sources_line", sources=sources))
        lines.append(f"  → {item['next_step']}")
    if len(findings) > limit:
        lines.append(BULLET + t(lang, "summary.more_items",
                                count=len(findings) - limit))
    return lines


def summarize(tool: str, result: dict[str, Any], lang: str) -> str:
    if result.get("error"):
        return t(lang, "summary.error", error=result["error"])

    if tool == "get_overview":
        counts, labels = result["counts"], result["labels"]
        cash = result["cashflow_totals"]
        lines = [
            t(lang, "summary.overview.head",
              statement_date=result["statement_date"],
              account_txns=counts["account_txns"],
              card_txns=counts["card_txns"], emails=counts["emails"]),
            t(lang, "summary.overview.tally",
              needs_confirmation=labels["needs_your_confirmation"],
              insufficient_data=labels["insufficient_data"],
              recurring_confirmed=labels["recurring_confirmed"]),
            t(lang, "summary.overview.money",
              payin=fmt_display(cash["payin_cents"], lang),
              spend=fmt_display(cash["spend_cents"], lang),
              fees=fmt_display(cash["fees_cents"], lang)),
            "",
        ]
        for item in result.get("alerts_preview", []):
            lines.append(f"{BULLET}[{item['label']}] {item['title']} "
                         f"({item['amount']})")
        return "\n".join(lines)

    if tool == "get_cashflow":
        lines = [t(lang, "summary.cashflow.head")]
        for bucket in result["account"].values():
            lines.append(BULLET + t(lang, "summary.cashflow.bucket_row",
                                    label=bucket["label"],
                                    count=bucket["count"],
                                    total=fmt_display(bucket["total_cents"],
                                                      lang)))
        lines.append("")
        lines.append(t(lang, "summary.cashflow.by_category"))
        for row in result["categories"][:6]:
            lines.append(f"{BULLET}{row['label']}: "
                         f"{fmt_display(row['total_cents'], lang)} ({row['count']})")
        return "\n".join(lines)

    if tool == "list_subscriptions":
        lines = [t(lang, "summary.subscriptions.head",
                   count=len(result["subscriptions"]))]
        for sub in result["subscriptions"]:
            lines.append(BULLET + t(
                lang, "summary.subscriptions.row",
                name=sub["merchant"] or sub["descriptor"],
                amount=fmt_display(sub["current_amount_cents"], lang),
                cadence=t(lang, "cadence." + sub["cadence"]),
                next_charge=sub["next_charge"],
                annual_cost=fmt_display(sub["annual_cost_cents"], lang),
            ))
        forecast = result.get("forecast", {})
        if forecast:
            lines.append("")
            lines.append(t(lang, "summary.subscriptions.forecast",
                           annual_projection=fmt_display(
                               forecast["annual_projection_cents"], lang)))
        if result.get("price_increases"):
            lines.append("")
            lines += _finding_lines(result["price_increases"], lang)
        return "\n".join(lines)

    if tool == "get_findings":
        if not result["findings"]:
            return t(lang, "summary.findings.none")
        head = t(lang, "summary.findings.head", count=result["count"])
        return "\n".join([head] + _finding_lines(result["findings"], lang))

    if tool == "get_email_recon":
        summary = result["summary"]
        lines = [t(lang, "summary.email_recon.head",
                   matched=summary["matched"],
                   no_email_found=summary["no_email_found"],
                   suspicious_emails=summary["suspicious_emails"])]
        for row in result["rows"][:10]:
            lines.append(f"{BULLET}{row['date']} {row['descriptor']} "
                         f"{row['amount']} — {row['status_text']}"
                         + (f" ({row['email_from']})" if row['email_from'] else ""))
        # The look-alike senders are listed by name, not just counted: several
        # of them match no transaction at all, so the table above never shows
        # them.
        if result.get("suspicious"):
            lines.append("")
            lines.append(t(lang, "summary.email_recon.suspicious_head"))
            for item in result["suspicious"]:
                head = (f"{BULLET}{item['date']} {item['from_addr']} — "
                        f"“{item['subject']}”")
                if item.get("claimed_brand"):
                    head += (" (" + t(lang, "summary.email_recon.claimed_brand",
                                      brand=item["claimed_brand"]) + ")")
                lines.append(head)
                if item.get("reasons_text"):
                    lines.append(f"  {item['reasons_text']}.")
            lines.append(t(lang, "summary.email_recon.note"))
        return "\n".join(lines)

    if tool == "get_tri_source":
        summary = result["transfer_summary"]
        wallet = result.get("wallet", {})
        lines = [t(lang, "summary.tri_source.head",
                   matched=summary["matched"], total=summary["total"],
                   not_on_card=summary["not_on_card"])]
        if wallet:
            computed = fmt_display(wallet["computed_cents"], lang)
            # No reported closing balance -> no gap to state. Saying so beats
            # printing a figure the statement never gave.
            if wallet.get("reported_cents") is None:
                lines.append(t(lang, "summary.tri_source.wallet_no_report",
                               computed=computed))
            else:
                lines.append(t(
                    lang, "summary.tri_source.wallet_gap", computed=computed,
                    reported=fmt_display(wallet["reported_cents"], lang),
                    gap=fmt_display(abs(wallet["gap_cents"]), lang),
                ))
        if result.get("findings"):
            lines.append("")
            lines += _finding_lines(result["findings"], lang)
        return "\n".join(lines)

    if tool == "get_report":
        period, totals = result["period"], result["totals"]
        comparison = result["comparison"]["spend"]
        lines = [t(lang, "summary.report.head", label=period["label"],
                   start=period["start"], end=period["end"])]
        for key, cents in (("purchase", totals["spend_cents"]),
                           ("fee", totals["fees_cents"]),
                           ("payin", totals["payin_cents"]),
                           ("payout", totals["payout_cents"])):
            lines.append(f"{BULLET}{t(lang, 'cashflow.' + key)}: "
                         f"{fmt_display(cents, lang)}")
        if comparison.get("percent") is not None:
            lines.append(BULLET + t(
                lang, "summary.report.comparison",
                period_key=result["comparison"]["period_key"],
                delta=fmt_display(comparison["delta_cents"], lang),
                percent=comparison["percent"],
            ))
        lines.append("")
        lines.append(t(lang, "summary.report.top_head"))
        for row in result["top_purchases"]:
            name = row["merchant"] or row["descriptor"]
            lines.append(f"{BULLET}{row['date']} {name}: "
                         f"{fmt_display(row['amount_cents'], lang)} [{row['ref']}]")
        return "\n".join(lines)

    if tool == "explain_charge":
        if not result.get("found"):
            return t(lang, "summary.explain.not_found")
        lines = []
        for row in result["matches"]:
            lines.append(f"{row['date']} — {row['descriptor']} {row['amount']} "
                         f"[{row['ref']}, {row['flow_label']}]")
            if row["merchant"]:
                merchant = row["merchant"]
                if row["merchant_explained"]:
                    merchant += f" — {row['merchant_explained']}"
                lines.append("  " + t(lang, "summary.explain.merchant",
                                      merchant=merchant))
            else:
                lines.append("  " + t(lang, "summary.explain.merchant_unknown"))
            if row["processor_hint"]:
                lines.append("  " + t(lang, "summary.explain.processor",
                                      processor=row["processor_hint"]))
            if row["email"]["status_text"]:
                detail = row["email"]["status_text"]
                if row["email"]["subject"]:
                    detail += f" — “{row['email']['subject']}”"
                lines.append(f"  Email: {detail}")
            if row["findings"]:
                lines += ["  " + line for line in _finding_lines(row["findings"],
                                                                 lang, 3)]
        return "\n".join(lines)

    if tool == "search_transactions":
        lines = [t(lang, "summary.search.head", matched=result["matched"],
                   shown=result["shown"],
                   total_spend=result["total_spend_of_matches"])]
        for row in result["rows"][:15]:
            name = row["merchant"] or row["descriptor"]
            lines.append(f"{BULLET}{row['date']} {name} {row['amount']} "
                         f"[{row['ref']}]")
        return "\n".join(lines)

    if tool == "get_reminders":
        if not result["reminders"]:
            return t(lang, "summary.reminders.none")
        lines = [t(lang, "summary.reminders.head", count=result["count"])]
        for row in result["reminders"]:
            lines.append(BULLET + t(lang, "summary.reminders.row",
                                    due_date=row["due_date"],
                                    days_left=row["days_left"],
                                    title=row["title"]))
        return "\n".join(lines)

    if tool == "run_monitor_scan":
        lines = [t(lang, "summary.monitor.head",
                   new_count=result["new_count"],
                   suppressed_count=result["suppressed_count"])]
        if result["new"]:
            lines += _finding_lines(result["new"], lang)
        return "\n".join(lines)

    if tool == "draft_report_email":
        return "\n".join([
            t(lang, "summary.draft.prepared", subject=result["subject"]),
            result["confirm_prompt"],
            "",
            result["body_preview"],
        ])

    if tool == "get_cancellation_guide":
        if not result.get("found"):
            return t(lang, "summary.cancel.which_plan",
                     available=", ".join(result.get("available", [])))
        guide = result["guide"]
        return "\n".join([
            t(lang, "summary.cancel.head", title=guide["title"],
              amount=result["amount"], next_charge=result["next_charge"]),
            guide["body"],
        ])

    if tool == "get_audit_log":
        lines = [t(lang, "summary.audit.head", count=result["count"])]
        for row in result["entries"]:
            lines.append(f"{BULLET}{row['logged_at'][:19]} {row['event']} "
                         f"{row['kind'] or ''} {row['label'] or ''} "
                         f"({row['confidence'] if row['confidence'] else '-'}) "
                         f"{row['reason'][:120]}")
        return "\n".join(lines)

    return t(lang, "summary.unsupported")
