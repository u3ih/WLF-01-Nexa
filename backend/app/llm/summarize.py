"""Deterministic answers.

Used when no model is reachable, and as the final fallback if a model reply
keeps breaking a hard rule. Every sentence here is built from engine output, so
it can never invent a figure.
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
        more = len(findings) - limit
        lines.append(BULLET + (f"… và {more} khoản nữa." if lang == "vi"
                               else f"… and {more} more items."))
    return lines


def summarize(tool: str, result: dict[str, Any], lang: str) -> str:
    vi = lang == "vi"
    if result.get("error"):
        return (f"Mình chưa lấy được dữ liệu này ({result['error']})."
                if vi else f"I could not read that data ({result['error']}).")

    if tool == "get_overview":
        counts, labels = result["counts"], result["labels"]
        cash = result["cashflow_totals"]
        head = (f"Sao kê ngày {result['statement_date']}: "
                f"{counts['account_txns']} dòng tài khoản, "
                f"{counts['card_txns']} dòng thẻ, {counts['emails']} email."
                if vi else
                f"Statement dated {result['statement_date']}: "
                f"{counts['account_txns']} account lines, "
                f"{counts['card_txns']} card lines, {counts['emails']} emails.")
        tally = (f"Đang có {labels['needs_your_confirmation']} khoản cần bạn tự "
                 f"xác nhận, {labels['insufficient_data']} khoản chưa đủ dữ liệu, "
                 f"{labels['recurring_confirmed']} khoản định kỳ đã xác định."
                 if vi else
                 f"{labels['needs_your_confirmation']} items need your "
                 f"confirmation, {labels['insufficient_data']} lack enough data, "
                 f"{labels['recurring_confirmed']} are confirmed recurring.")
        money = (f"Tiền vào {fmt_display(cash['payin_cents'], lang)}, chi tiêu "
                 f"{fmt_display(cash['spend_cents'], lang)}, phí "
                 f"{fmt_display(cash['fees_cents'], lang)}."
                 if vi else
                 f"Money in {fmt_display(cash['payin_cents'], lang)}, spending "
                 f"{fmt_display(cash['spend_cents'], lang)}, fees "
                 f"{fmt_display(cash['fees_cents'], lang)}.")
        lines = [head, tally, money, ""]
        for item in result.get("alerts_preview", []):
            lines.append(f"{BULLET}[{item['label']}] {item['title']} "
                         f"({item['amount']})")
        return "\n".join(lines)

    if tool == "get_cashflow":
        lines = ["Phân loại dòng tiền:" if vi else "Cash-flow breakdown:"]
        for key, bucket in result["account"].items():
            lines.append(f"{BULLET}{bucket['label']} — "
                         f"{bucket['count']} {'giao dịch' if vi else 'items'}, "
                         f"{fmt_display(bucket['total_cents'], lang)}")
        lines.append("")
        lines.append("Theo nhóm chi tiêu:" if vi else "By category:")
        for row in result["categories"][:6]:
            lines.append(f"{BULLET}{row['label']}: "
                         f"{fmt_display(row['total_cents'], lang)} ({row['count']})")
        return "\n".join(lines)

    if tool == "list_subscriptions":
        lines = [f"{len(result['subscriptions'])} "
                 + ("gói định kỳ đã xác định:" if vi
                    else "recurring plans identified:")]
        for sub in result["subscriptions"]:
            name = sub["merchant"] or sub["descriptor"]
            lines.append(f"{BULLET}{name}: "
                         f"{fmt_display(sub['current_amount_cents'], lang)} "
                         f"{t(lang, 'cadence.' + sub['cadence'])}, "
                         f"{'kỳ kế tiếp' if vi else 'next'} {sub['next_charge']}, "
                         f"{'cả năm' if vi else 'per year'} "
                         f"{fmt_display(sub['annual_cost_cents'], lang)}")
        forecast = result.get("forecast", {})
        if forecast:
            lines.append("")
            lines.append((f"Dự kiến tổng chi cho các gói trong 12 tháng: "
                          f"{fmt_display(forecast['annual_projection_cents'], lang)}."
                          if vi else
                          f"Projected 12-month subscription cost: "
                          f"{fmt_display(forecast['annual_projection_cents'], lang)}."))
        if result.get("price_increases"):
            lines.append("")
            lines += _finding_lines(result["price_increases"], lang)
        return "\n".join(lines)

    if tool == "get_findings":
        if not result["findings"]:
            return ("Với dữ liệu hiện có, mình chưa gắn cờ khoản nào theo tiêu chí "
                    "này. Đây không phải kết luận là mọi thứ đều đúng."
                    if vi else
                    "With the data available I flagged nothing under these "
                    "criteria. That is not a conclusion that everything is correct.")
        head = (f"{result['count']} khoản được gắn cờ:" if vi
                else f"{result['count']} flagged items:")
        return "\n".join([head] + _finding_lines(result["findings"], lang))

    if tool == "get_email_recon":
        summary = result["summary"]
        lines = [(f"Đối soát giao dịch ↔ email: {summary['matched']} có email khớp, "
                  f"{summary['no_email_found']} không tìm thấy email, "
                  f"{summary['suspicious_emails']} email nghi giả."
                  if vi else
                  f"Transaction-to-email: {summary['matched']} matched, "
                  f"{summary['no_email_found']} with no email, "
                  f"{summary['suspicious_emails']} suspicious emails.")]
        for row in result["rows"][:10]:
            lines.append(f"{BULLET}{row['date']} {row['descriptor']} "
                         f"{row['amount']} — {row['status_text']}"
                         + (f" ({row['email_from']})" if row['email_from'] else ""))
        # The look-alike senders are listed by name, not just counted: several
        # of them match no transaction at all, so the table above never shows
        # them.
        if result.get("suspicious"):
            lines.append("")
            lines.append("Email có người gửi giả danh:" if vi
                         else "Emails with an impersonated sender:")
            for item in result["suspicious"]:
                head = (f"{BULLET}{item['date']} {item['from_addr']} — "
                        f"“{item['subject']}”")
                if item.get("claimed_brand"):
                    head += (f" ({'tự nhận là' if vi else 'claims to be'} "
                             f"{item['claimed_brand']})")
                lines.append(head)
                if item.get("reasons_text"):
                    lines.append(f"  {item['reasons_text']}.")
            lines.append(("Đây là dấu hiệu người gửi không khớp thương hiệu, "
                          "không phải kết luận đã có gian lận. Đừng bấm link "
                          "trong các email này."
                          if vi else
                          "These are sender-identity mismatches, not a "
                          "conclusion that fraud occurred. Do not click the "
                          "links in these emails."))
        return "\n".join(lines)

    if tool == "get_tri_source":
        summary = result["transfer_summary"]
        wallet = result.get("wallet", {})
        lines = [(f"Đối chiếu 3 nguồn: {summary['matched']}/{summary['total']} "
                  f"khoản chuyển sang thẻ khớp với sao kê thẻ, "
                  f"{summary['not_on_card']} chưa thấy lên thẻ."
                  if vi else
                  f"Three-source check: {summary['matched']}/{summary['total']} "
                  f"card transfers matched a card load, "
                  f"{summary['not_on_card']} not on the card.")]
        if wallet:
            computed = fmt_display(wallet["computed_cents"], lang)
            # No reported closing balance -> no gap to state. Saying so beats
            # printing a figure the statement never gave.
            if wallet.get("reported_cents") is None:
                lines.append((f"Ví: sổ ví cộng ra {computed}; ví không báo số dư "
                              f"chốt nên chưa thể kết luận có lệch hay không."
                              if vi else
                              f"Wallet: ledger totals {computed}; the wallet "
                              f"reports no closing balance, so no gap can be "
                              f"asserted."))
            else:
                reported = fmt_display(wallet["reported_cents"], lang)
                gap = fmt_display(abs(wallet["gap_cents"]), lang)
                lines.append((f"Ví: sổ ví cộng ra {computed}, ví báo {reported} "
                              f"— lệch {gap}."
                              if vi else
                              f"Wallet: ledger totals {computed}, wallet reports "
                              f"{reported} — gap {gap}."))
        if result.get("findings"):
            lines.append("")
            lines += _finding_lines(result["findings"], lang)
        return "\n".join(lines)

    if tool == "get_report":
        period, totals = result["period"], result["totals"]
        comparison = result["comparison"]["spend"]
        lines = [(f"Báo cáo {period['label']} ({period['start']} → {period['end']}):"
                  if vi else
                  f"Report for {period['label']} ({period['start']} → "
                  f"{period['end']}):")]
        lines.append(f"{BULLET}{t(lang, 'cashflow.purchase')}: "
                     f"{fmt_display(totals['spend_cents'], lang)}")
        lines.append(f"{BULLET}{t(lang, 'cashflow.fee')}: "
                     f"{fmt_display(totals['fees_cents'], lang)}")
        lines.append(f"{BULLET}{t(lang, 'cashflow.payin')}: "
                     f"{fmt_display(totals['payin_cents'], lang)}")
        lines.append(f"{BULLET}{t(lang, 'cashflow.payout')}: "
                     f"{fmt_display(totals['payout_cents'], lang)}")
        if comparison.get("percent") is not None:
            lines.append(f"{BULLET}"
                         + ("So với " if vi else "vs ")
                         + f"{result['comparison']['period_key']}: "
                         f"{fmt_display(comparison['delta_cents'], lang)} "
                         f"({comparison['percent']}%)")
        lines.append("")
        lines.append("3 khoản lớn nhất:" if vi else "Top 3 purchases:")
        for row in result["top_purchases"]:
            name = row["merchant"] or row["descriptor"]
            lines.append(f"{BULLET}{row['date']} {name}: "
                         f"{fmt_display(row['amount_cents'], lang)} [{row['ref']}]")
        return "\n".join(lines)

    if tool == "explain_charge":
        if not result.get("found"):
            return ("Mình không tìm thấy giao dịch nào khớp trong dữ liệu này, "
                    "nên mình chưa có thông tin để trả lời."
                    if vi else
                    "I found no matching transaction in this data, so I do not "
                    "have the information to answer.")
        lines = []
        for row in result["matches"]:
            head = (f"{row['date']} — {row['descriptor']} {row['amount']} "
                    f"[{row['ref']}, {row['flow_label']}]")
            lines.append(head)
            if row["merchant"]:
                lines.append(f"  {'Cửa hàng' if vi else 'Merchant'}: "
                             f"{row['merchant']}"
                             + (f" — {row['merchant_explained']}"
                                if row["merchant_explained"] else ""))
            else:
                lines.append("  " + ("Cửa hàng: chưa xác định được — mình không "
                                     "đoán tên." if vi else
                                     "Merchant: could not be identified — I will "
                                     "not guess."))
            if row["processor_hint"]:
                lines.append(f"  {'Cổng thanh toán' if vi else 'Processor'}: "
                             f"{row['processor_hint']}")
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
        lines = [(f"Tìm thấy {result['matched']} giao dịch "
                  f"(hiện {result['shown']}), tổng chi "
                  f"{result['total_spend_of_matches']}:"
                  if vi else
                  f"{result['matched']} transactions found "
                  f"(showing {result['shown']}), total spend "
                  f"{result['total_spend_of_matches']}:")]
        for row in result["rows"][:15]:
            name = row["merchant"] or row["descriptor"]
            lines.append(f"{BULLET}{row['date']} {name} {row['amount']} "
                         f"[{row['ref']}]")
        return "\n".join(lines)

    if tool == "get_reminders":
        if not result["reminders"]:
            return ("Chưa có nhắc hạn nào. Chạy rà soát để tạo nhắc hạn."
                    if vi else
                    "No reminders yet. Run a scan to create them.")
        lines = [(f"{result['count']} nhắc hạn đang mở:" if vi
                  else f"{result['count']} open reminders:")]
        for row in result["reminders"]:
            lines.append(f"{BULLET}{row['due_date']} "
                         f"({row['days_left']} {'ngày' if vi else 'days'}) — "
                         f"{row['title']}")
        return "\n".join(lines)

    if tool == "run_monitor_scan":
        head = ((f"Đã rà soát lại: {result['new_count']} khoản mới, "
                 f"{result['suppressed_count']} khoản đã báo trước đó nên không "
                 f"báo lại.")
                if vi else
                (f"Re-scanned: {result['new_count']} new items, "
                 f"{result['suppressed_count']} already-reported items were not "
                 f"repeated."))
        lines = [head]
        if result["new"]:
            lines += _finding_lines(result["new"], lang)
        return "\n".join(lines)

    if tool == "draft_report_email":
        return "\n".join([
            (f"Đã soạn nháp báo cáo “{result['subject']}”." if vi
             else f"Draft report prepared: “{result['subject']}”."),
            result["confirm_prompt"],
            "",
            result["body_preview"],
        ])

    if tool == "get_cancellation_guide":
        if not result.get("found"):
            available = ", ".join(result.get("available", []))
            return (f"Bạn muốn huỷ gói nào? Đang có: {available}." if vi
                    else f"Which plan? Currently active: {available}.")
        guide = result["guide"]
        return "\n".join([
            f"{guide['title']} ({result['amount']}, "
            f"{'kỳ kế tiếp' if vi else 'next charge'} {result['next_charge']})",
            guide["body"],
        ])

    if tool == "get_audit_log":
        lines = [(f"{result['count']} dòng nhật ký gần nhất:" if vi
                  else f"{result['count']} most recent journal entries:")]
        for row in result["entries"]:
            lines.append(f"{BULLET}{row['logged_at'][:19]} {row['event']} "
                         f"{row['kind'] or ''} {row['label'] or ''} "
                         f"({row['confidence'] if row['confidence'] else '-'}) "
                         f"{row['reason'][:120]}")
        return "\n".join(lines)

    return ("Mình chưa có cách trình bày cho dữ liệu này." if vi
            else "I do not have a way to present this data.")
