"use client";

import { LabelBadge } from "@/components/Badges";
import { ui } from "@/lib/i18n";
import type { Lang } from "@/lib/types";

export function RemindersView({ data, lang }: { data: any; lang: Lang }) {
  if (!data.reminders.length) return <p className="empty">{ui(lang, "empty")}</p>;
  return (
    <table>
      <thead>
        <tr><th>Due</th><th>Left</th><th>Item</th><th className="num">Amount</th></tr>
      </thead>
      <tbody>
        {data.reminders.map((row: any) => (
          <tr key={row.id}>
            <td className="mono">{row.due_date}</td>
            <td className="num">
              <span className={row.expired ? "badge badge-danger" : "badge badge-confirm"}>
                {row.days_left} {ui(lang, "days")}
              </span>
            </td>
            <td>{row.title}</td>
            <td className="num">{row.amount}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function JournalView({ data, lang }: { data: any; lang: Lang }) {
  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 6,
                    marginBottom: 8 }}>
        <a className="btn btn-sm" href="/api/audit/export?format=csv">CSV</a>
        <a className="btn btn-sm" href="/api/audit/export?format=json">JSON</a>
      </div>
      <table>
        <thead>
          <tr><th>When</th><th>Event</th><th>Label</th>
            <th className="num">Conf.</th><th>Reason</th></tr>
        </thead>
        <tbody>
          {data.entries.map((row: any) => (
            <tr key={row.id}>
              <td className="mono">{row.logged_at?.slice(0, 19)}</td>
              <td>{row.event}</td>
              <td>{row.label ? <LabelBadge label={row.label} text={row.label} /> : "—"}</td>
              <td className="num">{row.confidence ?? "—"}</td>
              <td style={{ color: "var(--text-dim)", fontSize: 11.5 }}
                  className="mono">{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function StatementView({ data }: { data: any; lang: Lang }) {
  return (
    <table>
      <thead>
        <tr><th>#</th><th>Date</th><th>Type</th><th>Status</th><th>Descriptor</th>
          <th className="num">Amount</th><th className="num">Balance</th></tr>
      </thead>
      <tbody>
        {data.rows.map((row: any) => (
          <tr key={row.ref}>
            <td><span className="ref">{row.ref}</span></td>
            <td className="mono">{row.date}</td>
            <td><span className="badge badge-neutral">{row.type_label}</span></td>
            <td>
              {row.status && row.status !== "success" ? (
                <span className="badge badge-neutral">{row.status_label}</span>
              ) : null}
            </td>
            <td>{row.merchant ?? row.descriptor}</td>
            <td className="num">{row.amount}</td>
            <td className="num" style={{ color: "var(--text-faint)" }}>
              {/* Not every statement prints a running balance. */}
              {row.balance_after ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
