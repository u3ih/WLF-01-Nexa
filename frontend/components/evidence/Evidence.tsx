"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { LabelBadge } from "@/components/Badges";
import { AlertsView } from "@/components/evidence/AlertsView";
import { BoundariesView } from "@/components/evidence/BoundariesView";
import {
  CashflowView, ReportView, SubscriptionsView,
} from "@/components/evidence/MoneyViews";
import { EmailReconView, TriSourceView } from "@/components/evidence/ReconViews";
import {
  JournalView, RemindersView, StatementView,
} from "@/components/evidence/SystemViews";
import { api } from "@/lib/api";
import { ui } from "@/lib/i18n";
import type { EvidenceView, RefFocus } from "@/lib/refs";
import type { Lang, Summary } from "@/lib/types";

/** The data views, plus the one panel that describes the code instead. */
type ViewId = EvidenceView | "boundaries";

/** Nine sibling tabs gave the eye nothing to latch onto. Grouping asks one
 *  question first — alerts, money, proof, plumbing, or what it refuses — and
 *  only then which view inside it. */
const GROUPS: { id: string; key: string; views: ViewId[] }[] = [
  { id: "alerts", key: "grp_alerts", views: ["findings"] },
  { id: "money", key: "grp_money", views: ["cashflow", "report", "subs"] },
  { id: "recon", key: "grp_recon", views: ["email", "tri"] },
  { id: "system", key: "grp_system", views: ["reminders", "journal", "statement"] },
  { id: "safety", key: "grp_safety", views: ["boundaries"] },
];

const VIEW_LABEL: Record<ViewId, string> = {
  findings: "tab_findings",
  cashflow: "tab_cashflow",
  report: "tab_report",
  subs: "tab_subs",
  email: "tab_email",
  tri: "tab_tri",
  reminders: "tab_reminders",
  journal: "tab_journal",
  statement: "tab_statement",
  boundaries: "grp_safety",
};

export function Evidence({
  lang, summary, focus, refreshToken, onScan, onAsk,
}: {
  lang: Lang;
  summary: Summary | null;
  focus: RefFocus | null;
  refreshToken: number;
  onScan: (result: any) => void;
  onAsk: (question: string) => void;
}) {
  const [view, setView] = useState<ViewId>("findings");
  const [data, setData] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<"month" | "quarter" | "year">("month");
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<any>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (which: ViewId) => {
    // The safety panel describes the code rather than the dataset.
    if (which === "boundaries") return;
    setLoading(true);
    setError(null);
    try {
      const loaders: Record<Exclude<ViewId, "boundaries">, () => Promise<any>> = {
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

  useEffect(() => { load(view); }, [view, load, refreshToken]);

  useEffect(() => { if (focus) setView(focus.view); }, [focus]);

  // Reached through the DOM on purpose. The row lives in whichever of the nine
  // views is mounted, and threading one string plus a scroll callback through
  // all of them would be a wider change than the one query the panel that owns
  // the scroll container can make itself. `current` is in the dependency list
  // so this re-runs once the view's data has actually landed.
  useEffect(() => {
    const body = bodyRef.current;
    if (!body || !focus || view !== focus.view) return;
    body.querySelectorAll(".row-focus")
      .forEach((node) => node.classList.remove("row-focus"));
    const target = body.querySelector(`[data-ref~="${CSS.escape(focus.ref)}"]`);
    if (!target) return;
    target.classList.add("row-focus");
    target.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus, view, data]);

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

  const group = GROUPS.find((entry) => entry.views.includes(view)) ?? GROUPS[0];
  const current = data[view];

  function renderView() {
    if (view === "boundaries") return <BoundariesView lang={lang} onAsk={onAsk} />;
    if (!current) return <p className="empty">{ui(lang, "empty")}</p>;
    switch (view) {
      case "findings": return <AlertsView data={current} lang={lang} />;
      case "cashflow": return <CashflowView data={current} lang={lang} />;
      case "report": return <ReportView data={current} lang={lang} />;
      case "subs": return <SubscriptionsView data={current} lang={lang} />;
      case "email": return <EmailReconView data={current} lang={lang} />;
      case "tri": return <TriSourceView data={current} lang={lang} />;
      case "reminders": return <RemindersView data={current} lang={lang} />;
      case "journal": return <JournalView data={current} lang={lang} />;
      case "statement": return <StatementView data={current} lang={lang} />;
    }
  }

  return (
    <section className="card">
      <div className="tabs" role="tablist">
        {GROUPS.map((entry) => (
          <button
            key={entry.id}
            role="tab"
            aria-selected={group.id === entry.id}
            className="tab"
            onClick={() => setView(entry.views[0])}
          >
            {ui(lang, entry.key as never)}
          </button>
        ))}
      </div>

      {group.views.length > 1 ? (
        <div className="subtabs" role="tablist">
          {group.views.map((id) => (
            <button
              key={id}
              role="tab"
              aria-selected={view === id}
              className="subtab"
              onClick={() => setView(id)}
            >
              {ui(lang, VIEW_LABEL[id] as never)}
            </button>
          ))}
        </div>
      ) : null}

      <div className="card-head">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {/* Label tallies describe the findings, so they ride with the alerts. */}
          {summary && group.id === "alerts" ? (
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
          {view === "report"
            ? (["month", "quarter", "year"] as const).map((option) => (
              <button
                key={option}
                className={`btn btn-sm${period === option ? " btn-primary" : ""}`}
                onClick={() => setPeriod(option)}
              >
                {ui(lang, `period_${option}` as never)}
              </button>
            ))
            : null}
          {view === "boundaries" ? null : (
            <button className="btn btn-sm" onClick={runScan} disabled={scanning}>
              {scanning ? ui(lang, "scanning") : ui(lang, "scan")}
            </button>
          )}
        </div>
      </div>

      <div className="card-body" ref={bodyRef}>
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
        {renderView()}
      </div>
    </section>
  );
}
