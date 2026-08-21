"use client";

import { useCallback, useEffect, useState } from "react";

import { FindingCard, LabelBadge } from "@/components/Badges";
import { api } from "@/lib/api";
import { ui } from "@/lib/i18n";
import type { Finding, Lang, Summary } from "@/lib/types";

type TabId =
  | "findings" | "cashflow" | "email" | "tri" | "subs" | "report"
  | "reminders" | "journal" | "statement";

const TABS: { id: TabId; key: string }[] = [
  { id: "findings", key: "tab_findings" },
  { id: "cashflow", key: "tab_cashflow" },
  { id: "email", key: "tab_email" },
  { id: "tri", key: "tab_tri" },
  { id: "subs", key: "tab_subs" },
  { id: "report", key: "tab_report" },
  { id: "reminders", key: "tab_reminders" },
  { id: "journal", key: "tab_journal" },
  { id: "statement", key: "tab_statement" },
];

const STATUS_BADGE: Record<string, string> = {
  matched: "badge badge-recurring",
  no_email_found: "badge badge-confirm",
  email_suspicious: "badge badge-danger",
};

function Bar({ label, value, max, amount }: {
  label: string; value: number; max: number; amount: string;
}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="bar-row">
      <span>{label}</span>
      <span className="bar"><span style={{ width: `${pct}%` }} /></span>
      <span className="mono">{amount}</span>
    </div>
  );
}

function Trend({ series, lang }: { series: any[]; lang: Lang }) {
  if (!series?.length) return null;
  const max = Math.max(...series.map((row) => row.spend_usd ?? 0), 1);
  const width = 100 / series.length;
  return (
    <div>
      <div className="stat-k" style={{ marginBottom: 6 }}>{ui(lang, "trend")}</div>
      <svg viewBox="0 0 100 34" preserveAspectRatio="none"
           style={{ width: "100%", height: 90 }}>
        {series.map((row, index) => {
          const height = ((row.spend_usd ?? 0) / max) * 30;
          return (
            <g key={row.key}>
              <rect
                x={index * width + width * 0.18}
                y={32 - height}
                width={width * 0.64}
                height={Math.max(height, 0.4)}
                rx={0.6}
                fill="var(--accent)"
                opacity={index === series.length - 1 ? 1 : 0.55}
              />
            </g>
          );
        })}
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between",
                    color: "var(--text-faint)", fontSize: 10.5 }}>
        <span className="mono">{series[0].key}</span>
        <span className="mono">{series[series.length - 1].key}</span>
      </div>
    </div>
  );
}

export function Evidence({
  lang, summary, refreshToken, onScan,
}: {
  lang: Lang;
  summary: Summary | null;
  refreshToken: number;
  onScan: (result: any) => void;
}) {
  const [tab, setTab] = useState<TabId>("findings");
  const [data, setData] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<"month" | "quarter" | "year">("month");
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<any>(null);

  const load = useCallback(async (which: TabId) => {
    setLoading(true);
    setError(null);
    try {
      const loaders: Record<TabId, () => Promise<any>> = {
        findings: () => api.findings(lang),
        cashflow: () => api.cashflow(lang),
        email: () => api.emailRecon(lang),
        tri: () => api.triSource(lang),
        subs: () => api.subscriptions(lang),
        report: () => api.report(lang, period),
        reminders: () => api.reminders(lang),
        journal: () => api.audit(lang, 120),
        statement: () => api.statement(lang, "account"),
      };
      const result = await loaders[which]();
      setData((previous) => ({ ...previous, [which]: result }));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception));
    } finally {
      setLoading(false);
    }
  }, [lang, period]);

  useEffect(() => { load(tab); }, [tab, load, refreshToken]);

  async function runScan() {
    setScanning(true);
    try {
      const result = await api.scan(lang);
      setScanResult(result);
      onScan(result);
      await load("reminders");
      await load("journal");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception));
    } finally {
      setScanning(false);
    }
  }

  const current = data[tab];

  return (
    <section className="card">
      <div className="tabs" role="tablist">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            role="tab"
            aria-selected={tab === entry.id}
            className="tab"
            onClick={() => setTab(entry.id)}
          >
            {ui(lang, entry.key as never)}
          </button>
        ))}
      </div>

      <div className="card-head">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {summary ? (
            <>
              <LabelBadge
                label="needs_your_confirmation"
                text={`${summary.labels.needs_your_confirmation} · ${
                  summary.findings.find((f) => f.label === "needs_your_confirmation")
                    ?.label_text ?? ""}`}
              />
              <LabelBadge
                label="insufficient_data"
                text={`${summary.labels.insufficient_data} · ${
                  summary.findings.find((f) => f.label === "insufficient_data")
                    ?.label_text ?? ""}`}
              />
              <LabelBadge
                label="recurring_confirmed"
                text={`${summary.labels.recurring_confirmed} · ${
                  summary.findings.find((f) => f.label === "recurring_confirmed")
                    ?.label_text ?? ""}`}
              />
            </>
          ) : null}
          {loading ? <span className="spinner" /> : null}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {tab === "report" ? (
            <>
              {(["month", "quarter", "year"] as const).map((option) => (
                <button
                  key={option}
                  className={`btn btn-sm${period === option ? " btn-primary" : ""}`}
                  onClick={() => setPeriod(option)}
                >
                  {ui(lang, `period_${option}` as never)}
                </button>
              ))}
            </>
          ) : null}
          <button className="btn btn-sm" onClick={runScan} disabled={scanning}>
            {scanning ? ui(lang, "scanning") : ui(lang, "scan")}
          </button>
        </div>
      </div>

      <div className="card-body">
        {error ? <p className="err">{error}</p> : null}
        {scanResult ? (
          <p className="chip" style={{ marginBottom: 10 }}>
            <span className="k">scan #{scanResult.scan_id}</span>
            <span className="v">
              {scanResult.new_count} {ui(lang, "newFindings")}
            </span>
            <span className="k">
              · {scanResult.suppressed_count} {ui(lang, "suppressed")}
            </span>
          </p>
        ) : null}

        {!current ? (
          <p className="empty">{ui(lang, "empty")}</p>
        ) : tab === "findings" ? (
          <div className="scroll">
            {(current.findings as Finding[]).map((finding) => (
              <FindingCard key={finding.id} finding={finding} lang={lang} />
            ))}
            {!current.findings.length ? <p className="empty">{ui(lang, "empty")}</p> : null}
          </div>
        ) : tab === "cashflow" ? (
          <div>
            <div className="stat-grid" style={{ marginBottom: 12 }}>
              {[
                ["spend", current.totals.spend],
                ["fees", current.totals.fees],
                ["payin", current.totals.payin],
                ["payout", current.totals.payout],
                ["toCard", current.totals.transfer_to_card],
              ].map(([key, value]) => (
                <div className="stat" key={key as string}>
                  <div className="stat-k">{ui(lang, key as never)}</div>
                  <div className="stat-v">{value as string}</div>
                </div>
              ))}
            </div>
            <div className="scroll-sm">
              {current.categories.map((row: any) => (
                <Bar
                  key={row.category}
                  label={row.label}
                  value={row.total_usd}
                  max={Math.max(...current.categories.map((r: any) => r.total_usd))}
                  amount={row.total}
                />
              ))}
            </div>
          </div>
        ) : tab === "email" ? (
          <div>
            <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
              <span className="chip"><span className="k">{ui(lang, "matched")}</span>
                <span className="v mono">{current.summary.matched}</span></span>
              <span className="chip"><span className="k">{ui(lang, "noEmail")}</span>
                <span className="v mono">{current.summary.no_email_found}</span></span>
              <span className="chip"><span className="k">{ui(lang, "suspicious")}</span>
                <span className="v mono">{current.summary.suspicious_emails}</span></span>
            </div>
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th>#</th><th>Date</th><th>Descriptor</th>
                    <th className="num">Amount</th><th>Status</th><th>Email</th>
                  </tr>
                </thead>
                <tbody>
                  {current.rows.map((row: any) => (
                    <tr key={row.ref}>
                      <td><span className="ref">{row.ref}</span></td>
                      <td className="mono">{row.date}</td>
                      <td>{row.merchant ?? row.descriptor}</td>
                      <td className="num">{row.amount}</td>
                      <td>
                        <span className={STATUS_BADGE[row.status] ?? "badge badge-neutral"}>
                          {row.status_text}
                        </span>
                      </td>
                      <td style={{ color: "var(--text-faint)" }}>
                        {row.email_from ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : tab === "tri" ? (
          <div>
            <div className="stat-grid" style={{ marginBottom: 12 }}>
              <div className="stat">
                <div className="stat-k">{ui(lang, "toCard")}</div>
                <div className="stat-v">
                  {current.transfer_summary.matched}/{current.transfer_summary.total}
                </div>
                <div className="stat-sub">
                  {current.transfer_summary.not_on_card} {ui(lang, "notOnCard")}
                </div>
              </div>
              <div className="stat">
                <div className="stat-k">{ui(lang, "walletGap")}</div>
                <div className="stat-v">{current.wallet?.gap}</div>
                <div className="stat-sub">{current.wallet?.reported_at}</div>
              </div>
            </div>
            {(current.findings as Finding[]).map((finding) => (
              <FindingCard key={finding.id} finding={finding} lang={lang} />
            ))}
            <div className="scroll-sm" style={{ marginTop: 12 }}>
              <table>
                <thead>
                  <tr><th>#</th><th>Date</th><th className="num">Amount</th>
                    <th>Card ref</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {current.transfers.map((row: any) => (
                    <tr key={row.txn_id}>
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
            </div>
          </div>
        ) : tab === "subs" ? (
          <div>
            <div className="scroll-sm">
              <table>
                <thead>
                  <tr><th>Plan</th><th className="num">Amount</th>
                    <th>{ui(lang, "nextCharge")}</th>
                    <th className="num">{ui(lang, "perYear")}</th>
                    <th className="num">#</th></tr>
                </thead>
                <tbody>
                  {current.subscriptions.map((sub: any) => (
                    <tr key={sub.merchant_key}>
                      <td>
                        {sub.merchant ?? sub.descriptor}
                        <div style={{ color: "var(--text-faint)", fontSize: 11 }}
                             className="mono">{sub.descriptor}</div>
                      </td>
                      <td className="num">{sub.current_amount}</td>
                      <td className="mono">{sub.next_charge}</td>
                      <td className="num">{sub.annual_cost}</td>
                      <td className="num">{sub.charge_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 12 }}>
              {(current.price_increases as Finding[]).map((finding) => (
                <FindingCard key={finding.id} finding={finding} lang={lang} />
              ))}
            </div>
          </div>
        ) : tab === "report" ? (
          <div>
            <div className="stat-grid" style={{ marginBottom: 12 }}>
              <div className="stat">
                <div className="stat-k">{ui(lang, "spend")}</div>
                <div className="stat-v">{current.totals.spend}</div>
                <div className="stat-sub">
                  {ui(lang, "vs")} {current.comparison.period_key}:{" "}
                  {current.comparison.spend.delta}{" "}
                  {current.comparison.spend.percent !== null
                    ? `(${current.comparison.spend.percent}%)` : ""}
                </div>
              </div>
              <div className="stat">
                <div className="stat-k">{ui(lang, "fees")}</div>
                <div className="stat-v">{current.totals.fees}</div>
              </div>
              <div className="stat">
                <div className="stat-k">{ui(lang, "payin")}</div>
                <div className="stat-v">{current.totals.payin}</div>
              </div>
              <div className="stat">
                <div className="stat-k">{ui(lang, "payout")}</div>
                <div className="stat-v">{current.totals.payout}</div>
              </div>
            </div>
            <Trend series={current.trend} lang={lang} />
            <div className="stat-k" style={{ margin: "12px 0 4px" }}>
              {ui(lang, "top3")}
            </div>
            <table>
              <tbody>
                {current.top_purchases.map((row: any) => (
                  <tr key={row.ref}>
                    <td className="mono">{row.date}</td>
                    <td>{row.merchant ?? row.descriptor}</td>
                    <td className="num">{row.amount}</td>
                    <td><span className="ref">{row.ref}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : tab === "reminders" ? (
          <div className="scroll">
            <table>
              <thead>
                <tr><th>Due</th><th>Left</th><th>Item</th><th className="num">Amount</th></tr>
              </thead>
              <tbody>
                {current.reminders.map((row: any) => (
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
            {!current.reminders.length ? <p className="empty">{ui(lang, "empty")}</p> : null}
          </div>
        ) : tab === "journal" ? (
          <div className="scroll">
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
                {current.entries.map((row: any) => (
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
          </div>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr><th>#</th><th>Date</th><th>Type</th><th>Descriptor</th>
                  <th className="num">Amount</th><th className="num">Balance</th></tr>
              </thead>
              <tbody>
                {current.rows.map((row: any) => (
                  <tr key={row.ref}>
                    <td><span className="ref">{row.ref}</span></td>
                    <td className="mono">{row.date}</td>
                    <td><span className="badge badge-neutral">{row.type_label}</span></td>
                    <td>{row.merchant ?? row.descriptor}</td>
                    <td className="num">{row.amount}</td>
                    <td className="num" style={{ color: "var(--text-faint)" }}>
                      {row.balance_after}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
