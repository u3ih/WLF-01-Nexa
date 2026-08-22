"use client";

import {
  Check, Copy, CornerDownRight, Info, RotateCcw, ShieldAlert, ShieldQuestion,
} from "lucide-react";
import { useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

import { FindingCard, labelClass } from "@/components/Badges";
import { Ref, RefText, type OnRef } from "@/components/RefText";
import { SAMPLE_QUESTIONS, ui } from "@/lib/i18n";
import {
  collectFindings, findingFor, parseEngineText, parseSources,
  type EngineItem,
} from "@/lib/engineText";
import { isModelAuthored } from "@/lib/markdown";
import { collectRefs, refPattern, rehypeRefs } from "@/lib/refs";
import type { ChatReply, Finding, Lang } from "@/lib/types";

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

/* ------------------------------------------------------------ model prose */

/** A cell holding nothing but one amount — currency mark, digits, separators,
 *  a percent or a sign, and a bare `–` for the empty cell. Anchored so a
 *  sentence that merely opens with a figure ("$300.00 was refunded") is prose
 *  and wraps like prose; only the amount column gets the numeric treatment. */
const NUMERIC_CELL = /^[-+–—(]?\s*[$€£¥₫]?\s*\d[\d,. ]*\s*[%)]?\s*[$€£¥₫]?$|^[-–—]$/;

/** react-markdown hands a cell its children, not its text. Flatten the strings
 *  it did render; anything with markup inside (a marked reference, a bolded
 *  note) is not a bare amount and falls through to prose. */
function cellText(children: any): string | null {
  if (typeof children === "string" || typeof children === "number") {
    return String(children);
  }
  if (Array.isArray(children)) {
    const parts = children.map(cellText);
    return parts.every((p) => p !== null) ? parts.join("") : null;
  }
  return null;
}

function isNumericCell(children: any): boolean {
  const text = cellText(children)?.trim();
  return !!text && NUMERIC_CELL.test(text);
}

function markdownComponents(onRef: OnRef, refTitle: string) {
  return {
    // Tables are the one thing a model can emit that is wider than the column.
    table: (props: any) => (
      <div className="prose-table"><table {...props} /></div>
    ),
    // An amount is a figure, not a phrase: it keeps one line and lines up with
    // the amounts above it. Everything else in the row wraps as prose.
    td: ({ node, className, children, ...props }: any) => (
      <td
        className={[className, isNumericCell(children) && "num"]
          .filter(Boolean).join(" ") || undefined}
        {...props}
      >
        {children}
      </td>
    ),
    // Addresses stay text. GFM auto-links bare email addresses, and the
    // addresses this assistant prints come out of the mailbox it is auditing —
    // including `no-reply@netfl1x-billing.com`, from the finding that calls
    // that sender an impersonation. Offering a click-through to an address the
    // same sentence flags as fraudulent is the one thing this UI must not do.
    a: (props: any) => <>{props.children}</>,
    // Transaction references are the exception, and they are not links: the
    // rehype pass below marks only the references the tool result contains, and
    // the control they become opens a local panel, never a network request.
    span: ({ node, ...props }: any) => (
      props["data-ref"]
        ? <Ref value={props["data-ref"]} onRef={onRef} title={refTitle} />
        : <span {...props} />
    ),
  };
}

/* ----------------------------------------------------------- engine prose */

function EngineItemCard({ item, findings, deadlines, labelKeys, lang, onRef,
  pattern, refTitle }: {
    item: EngineItem;
    findings: Finding[];
    deadlines: Set<string>;
    labelKeys: Record<string, string>;
    lang: Lang;
    onRef: OnRef;
    pattern: RegExp | null;
    refTitle: string;
  }) {
  // A bullet the engine rendered from a finding has the whole finding sitting
  // in the tool result beside it — verdict, deadline, references and all. Draw
  // that, not the flattened text, so a chat answer and the evidence panel show
  // the same card.
  const finding = findingFor(item, findings);
  if (finding) {
    return <FindingCard finding={finding} lang={lang} onRef={onRef}
      refTitle={refTitle} />;
  }

  const sources = item.sources ? parseSources(item.sources) : [];
  return (
    <article className="answer-item">
      <header className="answer-head">
        {item.label ? (
          <span className={labelClass(labelKeys[item.label])}>
            <span className="badge-dot" />
            {item.label}
          </span>
        ) : null}
        <span className="answer-title">
          <RefText text={item.title} pattern={pattern} onRef={onRef}
            title={refTitle} />
        </span>
      </header>
      {item.detail ? (
        <p className="answer-detail">
          <RefText text={item.detail} pattern={pattern} onRef={onRef}
            title={refTitle} />
        </p>
      ) : null}
      {item.meta.map((line, index) => (
        <p key={index}
          className={deadlines.has(line) ? "finding-deadline" : "answer-meta"}>
          <RefText text={line} pattern={pattern} onRef={onRef} title={refTitle} />
        </p>
      ))}
      {sources.length ? (
        <p className="answer-sources">
          <span className="k">{ui(lang, "sources")}</span>
          {sources.map((source, index) => (
            <span className="chip" key={`${source.ref}-${index}`}>
              {source.kind ? <span className="k">{source.kind}</span> : null}
              <Ref value={source.ref} onRef={onRef} title={refTitle} />
            </span>
          ))}
        </p>
      ) : null}
      {item.next ? (
        <p className="finding-next">
          <strong>{ui(lang, "nextStep")}: </strong>
          <RefText text={item.next} pattern={pattern} onRef={onRef}
            title={refTitle} />
        </p>
      ) : null}
    </article>
  );
}

/** An answer the engine wrote, drawn from its own line grammar.
 *
 *  Text goes in as text — never through the markdown parser. Merchant
 *  descriptors are copied verbatim from the statement and contain asterisks
 *  (`PP*ZTRDNG LLC 8552`), and two of them in a paragraph pair up into emphasis
 *  and silently rewrite the descriptor.
 */
function EngineAnswer({ text, reply, lang, onRef, pattern, refTitle }: {
  text: string;
  reply: ChatReply | undefined;
  lang: Lang;
  onRef: OnRef;
  pattern: RegExp | null;
  refTitle: string;
}) {
  const blocks = useMemo(() => parseEngineText(text), [text]);
  const findings = useMemo(() => collectFindings(reply?.data), [reply?.data]);
  const deadlines = useMemo(
    () => new Set(findings.map((f) => f.dispute?.text).filter(Boolean) as string[]),
    [findings],
  );
  // The verdict is printed in the user's language; its colour is keyed on the
  // code behind it, which the reply carries alongside.
  const labelKeys = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [key, text_] of Object.entries(reply?.labels ?? {})) out[text_] = key;
    return out;
  }, [reply?.labels]);

  return (
    <div className="answer">
      {blocks.map((block, index) => {
        if (block.kind === "para") {
          return (
            <p className="answer-para" key={index}>
              {block.lines.map((line, position) => (
                <span key={position}>
                  {position > 0 ? <br /> : null}
                  <RefText text={line} pattern={pattern} onRef={onRef}
                    title={refTitle} />
                </span>
              ))}
            </p>
          );
        }
        // Single-line bullets are a list; bullets carrying a verdict, a
        // deadline and a next step are cards. Runs keep the two apart without
        // reordering anything.
        const runs: { simple: boolean; items: EngineItem[] }[] = [];
        for (const item of block.items) {
          const simple = !item.label && !item.detail && !item.meta.length
            && !item.sources && !item.next;
          const last = runs[runs.length - 1];
          if (last && last.simple === simple) last.items.push(item);
          else runs.push({ simple, items: [item] });
        }
        return (
          <div key={index}>
            {runs.map((run, position) => run.simple ? (
              <ul className="answer-list" key={position}>
                {run.items.map((item, row) => (
                  <li key={row}>
                    <RefText text={item.title} pattern={pattern} onRef={onRef}
                      title={refTitle} />
                  </li>
                ))}
              </ul>
            ) : (
              <div className="answer-cards" key={position}>
                {run.items.map((item, row) => (
                  <EngineItemCard
                    key={row}
                    item={item}
                    findings={findings}
                    deadlines={deadlines}
                    labelKeys={labelKeys}
                    lang={lang}
                    onRef={onRef}
                    pattern={pattern}
                    refTitle={refTitle}
                  />
                ))}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- the turn */

export function AssistantTurn({
  lang, text, reply, onAsk, onRetry, onRef,
}: {
  lang: Lang;
  text: string;
  reply?: ChatReply;
  onAsk: (question: string) => void;
  onRetry?: () => void;
  onRef?: (ref: string, tool: string | null) => void;
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

  // Only references the tool result actually contains become controls, so a
  // reference the model mistyped stays inert text.
  const pattern = useMemo(
    () => refPattern(collectRefs(reply?.data)), [reply?.data],
  );
  const tool = reply?.tool ?? null;
  const openRef: OnRef = onRef ? (ref: string) => onRef(ref, tool) : undefined;
  const refTitle = ui(lang, "openRef");

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

  const body = isModelAuthored(reply?.source) ? (
    <div className="prose">
      <Markdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        rehypePlugins={[rehypeRefs(pattern)]}
        components={markdownComponents(openRef, refTitle)}
      >
        {text}
      </Markdown>
    </div>
  ) : (
    <EngineAnswer text={text} reply={reply} lang={lang} onRef={openRef}
      pattern={pattern} refTitle={refTitle} />
  );

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
              <span className="badge badge-nodata line-clamp-1">
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
