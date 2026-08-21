"use client";

import type { Dispute, Finding, Lang, Source } from "@/lib/types";
import { ui } from "@/lib/i18n";

const LABEL_CLASS: Record<string, string> = {
  recurring_confirmed: "badge badge-recurring",
  needs_your_confirmation: "badge badge-confirm",
  insufficient_data: "badge badge-nodata",
};

export function LabelBadge({ label, text }: { label: string; text: string }) {
  return (
    <span className={LABEL_CLASS[label] ?? "badge badge-neutral"}>
      <span className="badge-dot" />
      {text}
    </span>
  );
}

export function DeadlineChip({ dispute, lang }: { dispute: Dispute; lang: Lang }) {
  if (!dispute?.dispute_deadline) return null;
  const days = dispute.days_left ?? 0;
  return (
    <span
      className={dispute.expired ? "badge badge-danger" : "chip"}
      title={dispute.text}
    >
      <span className="k">60d</span>
      <span className="v">{dispute.dispute_deadline}</span>
      <span className="k">
        {dispute.expired
          ? ui(lang, "overdue")
          : `${ui(lang, "dueIn")} ${days} ${ui(lang, "days")}`}
      </span>
    </span>
  );
}

export function SourceChips({ sources }: { sources: Source[] }) {
  if (!sources?.length) return null;
  return (
    <>
      {sources.map((source, index) => (
        <span className="chip" key={`${source.ref}-${index}`} title={source.detail}>
          <span className="k">{source.kind_text}</span>
          <span className="v mono">{source.ref.replace(/^<|>$/g, "").slice(0, 22)}</span>
        </span>
      ))}
    </>
  );
}

export function ConfidenceChip({ value, lang }: { value: number; lang: Lang }) {
  return (
    <span className="chip">
      <span className="k">{ui(lang, "confidence")}</span>
      <span className="v mono">{Math.round(value * 100)}%</span>
    </span>
  );
}

export function FindingCard({ finding, lang }: { finding: Finding; lang: Lang }) {
  return (
    <article className="finding">
      <header className="finding-head">
        <span className="finding-title">{finding.title}</span>
        <LabelBadge label={finding.label} text={finding.label_text} />
      </header>
      <p className="finding-detail">{finding.detail}</p>
      {finding.dispute?.text ? (
        <p className="finding-detail" style={{ color: "var(--label-confirm)" }}>
          {finding.dispute.text}
        </p>
      ) : null}
      <p className="finding-next">
        <strong>{ui(lang, "nextStep")}: </strong>
        {finding.next_step}
      </p>
      <footer className="finding-foot">
        <span className="chip">
          <span className="k">{ui(lang, "spend")}</span>
          <span className="v mono">{finding.amount}</span>
        </span>
        <ConfidenceChip value={finding.confidence} lang={lang} />
        <SourceChips sources={finding.sources} />
        {finding.txn_ids.length ? (
          <span className="chip" title={finding.txn_ids.join(", ")}>
            <span className="k">{ui(lang, "refs")}</span>
            <span className="v mono">
              {finding.txn_ids.slice(0, 3).join(", ")}
              {finding.txn_ids.length > 3 ? ` +${finding.txn_ids.length - 3}` : ""}
            </span>
          </span>
        ) : null}
      </footer>
    </article>
  );
}
