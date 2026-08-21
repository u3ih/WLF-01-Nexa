"use client";

import { FindingCard } from "@/components/Badges";
import { ui } from "@/lib/i18n";
import type { Finding, Lang } from "@/lib/types";

const STATUS_BADGE: Record<string, string> = {
  matched: "badge badge-recurring",
  no_email_found: "badge badge-confirm",
  email_suspicious: "badge badge-danger",
};

export function EmailReconView({ data, lang }: { data: any; lang: Lang }) {
  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <span className="chip"><span className="k">{ui(lang, "matched")}</span>
          <span className="v mono">{data.summary.matched}</span></span>
        <span className="chip"><span className="k">{ui(lang, "noEmail")}</span>
          <span className="v mono">{data.summary.no_email_found}</span></span>
        <span className="chip"><span className="k">{ui(lang, "suspicious")}</span>
          <span className="v mono">{data.summary.suspicious_emails}</span></span>
      </div>
      <table>
        <thead>
          <tr>
            <th>#</th><th>Date</th><th>Descriptor</th>
            <th className="num">Amount</th><th>Status</th><th>Email</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row: any) => (
            <tr key={row.ref} data-ref={row.ref}>
              <td><span className="ref">{row.ref}</span></td>
              <td className="mono">{row.date}</td>
              <td>{row.merchant ?? row.descriptor}</td>
              <td className="num">{row.amount}</td>
              <td>
                <span className={STATUS_BADGE[row.status] ?? "badge badge-neutral"}>
                  {row.status_text}
                </span>
              </td>
              <td style={{ color: "var(--text-faint)" }}>{row.email_from ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function TriSourceView({ data, lang }: { data: any; lang: Lang }) {
  return (
    <>
      <div className="stat-grid" style={{ marginBottom: 12 }}>
        <div className="stat">
          <div className="stat-k">{ui(lang, "toCard")}</div>
          <div className="stat-v">
            {data.transfer_summary.matched}/{data.transfer_summary.total}
          </div>
          <div className="stat-sub">
            {data.transfer_summary.not_on_card} {ui(lang, "notOnCard")}
          </div>
        </div>
        <div className="stat">
          <div className="stat-k">{ui(lang, "walletGap")}</div>
          <div className="stat-v">{data.wallet?.gap}</div>
          <div className="stat-sub">{data.wallet?.reported_at}</div>
        </div>
      </div>
      {(data.findings as Finding[]).map((finding) => (
        <FindingCard key={finding.id} finding={finding} lang={lang} />
      ))}
      <table style={{ marginTop: 12 }}>
        <thead>
          <tr><th>#</th><th>Date</th><th className="num">Amount</th>
            <th>Card ref</th><th>Status</th></tr>
        </thead>
        <tbody>
          {data.transfers.map((row: any) => (
            // Both legs, so a reference cited from either side finds this row.
            <tr key={row.txn_id}
                data-ref={[row.txn_id, row.card_ref].filter(Boolean).join(" ")}>
              <td><span className="ref">{row.txn_id}</span></td>
              <td className="mono">{row.date}</td>
              <td className="num">{row.amount}</td>
              <td className="mono">{row.card_ref ?? "—"}</td>
              <td>
                <span className={row.status === "matched"
                  ? "badge badge-recurring" : "badge badge-confirm"}>
                  {row.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
