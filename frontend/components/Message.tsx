"use client";

import {
  Check, Copy, CornerDownRight, Info, RotateCcw, ShieldAlert, ShieldQuestion,
} from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import { SAMPLE_QUESTIONS, ui } from "@/lib/i18n";
import { toMarkdown } from "@/lib/markdown";
import type { ChatReply, Lang } from "@/lib/types";

const PROVENANCE: Record<string, string> = {
  llm: "prov_llm",
  llm_retry: "prov_llm_retry",
  deterministic: "prov_deterministic",
  deterministic_fallback: "prov_deterministic_fallback",
  llm_unavailable: "prov_llm_unavailable",
  llm_error: "prov_llm_error",
  smalltalk_canned: "prov_smalltalk_canned",
  guardrail: "prov_guardrail",
};

const BOUNDARY_INTENTS = [
  "cancel_subscription", "third_party_email", "dispute",
  "money_move", "card_lock", "reassurance",
];

/** A refusal that ends the conversation is a dead end. Each boundary points at
 *  one thing the assistant is allowed to do, by index into the sample questions
 *  so the follow-up is always a phrasing the router already handles. */
const FOLLOW_UP: Record<string, number> = {
  cancel_subscription: 3,
  third_party_email: 5,
  dispute: 4,
  money_move: 2,
  card_lock: 4,
  reassurance: 4,
};

const MARKDOWN_COMPONENTS = {
  // Tables are the one thing a model can emit that is wider than the column.
  table: (props: any) => (
    <div className="prose-table"><table {...props} /></div>
  ),
  // Addresses stay text. GFM auto-links bare email addresses, and the addresses
  // this assistant prints come out of the mailbox it is auditing — including
  // `no-reply@netfl1x-billing.com`, from the finding that calls that sender an
  // impersonation. Offering a click-through to an address the same sentence
  // flags as fraudulent is the one thing this UI must not do. Nothing here ever
  // needs to be clickable: every source is a local sample file.
  a: (props: any) => <>{props.children}</>,
};

function Prose({ text, source }: { text: string; source: string | undefined }) {
  return (
    <div className="prose">
      <Markdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        components={MARKDOWN_COMPONENTS}
      >
        {toMarkdown(text, source)}
      </Markdown>
    </div>
  );
}

export function AssistantTurn({
  lang, text, reply, onAsk, onRetry,
}: {
  lang: Lang;
  text: string;
  reply?: ChatReply;
  onAsk: (question: string) => void;
  onRetry?: () => void;
}) {
  const [metaOpen, setMetaOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* clipboard denied — nothing useful to say about it */ }
  }

  // Read from guardrail.blocked, not from refused: the reassurance intent is a
  // soft block that answers with label counts, so it reports refused === false
  // while still being the guardrail talking.
  const guardrail = reply?.guardrail;
  const blocked = guardrail?.blocked === true;
  const hard = guardrail?.severity === "hard";
  const intent = guardrail?.intent && BOUNDARY_INTENTS.includes(guardrail.intent)
    ? guardrail.intent : null;
  const followUp = intent !== null && FOLLOW_UP[intent] !== undefined
    ? SAMPLE_QUESTIONS[lang][FOLLOW_UP[intent]] : null;
  const rejected = reply?.checks?.ungrounded_numbers ?? [];

  const body = <Prose text={text} source={reply?.source} />;

  return (
    <div className="ai-body">
      {blocked ? (
        <div className={`boundary boundary-${hard ? "hard" : "soft"}`}>
          <div className="boundary-head">
            {hard ? <ShieldAlert size={17} /> : <ShieldQuestion size={17} />}
            <span className="boundary-title">
              {ui(lang, hard ? "boundaryHard" : "boundarySoft")}
            </span>
            {intent ? (
              <span className={`badge ${hard ? "badge-confirm" : "badge-nodata"}`}>
                {ui(lang, `boundary_${intent}` as never)}
              </span>
            ) : null}
          </div>
          {body}
          {followUp ? (
            <button className="boundary-next" onClick={() => onAsk(followUp)}>
              <CornerDownRight size={14} />
              <span>
                <span className="boundary-next-k">{ui(lang, "boundaryNext")}</span>{" "}
                {followUp}
              </span>
            </button>
          ) : null}
        </div>
      ) : body}

      {reply ? (
        <>
          <div className="actions">
            <button className="act" onClick={copy}>
              {copied ? <Check size={13} /> : <Copy size={13} />}
              {ui(lang, copied ? "copied" : "copy")}
            </button>
            <button
              className="act"
              onClick={() => setMetaOpen(!metaOpen)}
              aria-pressed={metaOpen}
            >
              <Info size={13} />
              {ui(lang, "provenance")}
            </button>
            {onRetry ? (
              <button className="act" onClick={onRetry}>
                <RotateCcw size={13} />
                {ui(lang, "retry")}
              </button>
            ) : null}
            {/* Never folded away: this is the grounding check reporting that it
                caught the model citing a figure the engine never produced. */}
            {rejected.length ? (
              <span className="badge badge-nodata">
                {ui(lang, "rejectedFigures")}: {rejected.join(", ")}
              </span>
            ) : null}
          </div>

          {metaOpen ? (
            <div className="msg-meta">
              <span className="chip">
                <span className="k">{ui(lang, "provenance")}</span>
                <span className="v">
                  {ui(lang, (PROVENANCE[reply.source] ?? "prov_deterministic") as never)}
                </span>
              </span>
              {reply.tool ? (
                <span className="chip">
                  <span className="k">tool</span>
                  <span className="v mono">{reply.tool}</span>
                </span>
              ) : null}
              {reply.routed_by ? (
                <span className="chip">
                  <span className="k">router</span>
                  <span className="v mono">{reply.routed_by}</span>
                </span>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
