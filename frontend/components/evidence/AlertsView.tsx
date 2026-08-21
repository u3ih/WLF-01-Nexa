"use client";

import { FindingCard } from "@/components/Badges";
import { ui } from "@/lib/i18n";
import type { Finding, Lang } from "@/lib/types";

export function AlertsView({ data, lang }: { data: any; lang: Lang }) {
  const findings = (data.findings ?? []) as Finding[];
  if (!findings.length) return <p className="empty">{ui(lang, "empty")}</p>;
  return (
    <>
      {findings.map((finding) => (
        <FindingCard key={finding.id} finding={finding} lang={lang} />
      ))}
    </>
  );
}
