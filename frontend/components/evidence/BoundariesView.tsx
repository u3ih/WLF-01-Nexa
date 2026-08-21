"use client";

import { Play, ShieldAlert, ShieldQuestion } from "lucide-react";

import { BOUNDARIES, ui } from "@/lib/i18n";
import type { Lang } from "@/lib/types";

/** The whole refusal surface in one place. Every row runs a phrase that has
 *  been checked to trigger that intent, so the claim on the row and the
 *  behaviour a click produces cannot drift apart. */
export function BoundariesView({ lang, onAsk }: {
  lang: Lang;
  onAsk: (question: string) => void;
}) {
  return (
    <>
      <p className="panel-intro">{ui(lang, "boundaryIntro")}</p>
      {BOUNDARIES[lang].map((item) => {
        const hard = item.severity === "hard";
        const Icon = hard ? ShieldAlert : ShieldQuestion;
        return (
          <article className={`rule rule-${item.severity}`} key={item.intent}>
            <header className="rule-head">
              <Icon size={16} />
              <span className="rule-title">
                {ui(lang, `boundary_${item.intent}` as never)}
              </span>
              <span className={`badge ${hard ? "badge-confirm" : "badge-nodata"}`}>
                {ui(lang, hard ? "sev_hard" : "sev_soft")}
              </span>
            </header>
            <p className="rule-why">
              {ui(lang, `boundaryWhy_${item.intent}` as never)}
            </p>
            <footer className="rule-foot">
              <button className="btn btn-sm" onClick={() => onAsk(item.question)}>
                <Play size={12} />
                {ui(lang, "boundaryTry")}
              </button>
              <span className="rule-probe">“{item.question}”</span>
            </footer>
          </article>
        );
      })}
    </>
  );
}
