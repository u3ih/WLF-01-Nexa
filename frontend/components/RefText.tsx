"use client";

import { normaliseRef } from "@/lib/refs";

/** Absent when the surrounding view has nowhere to open a reference — a
 *  printed report, or a finding card drawn outside the conversation. The
 *  reference then stays text, which is why this is a union with undefined
 *  rather than an optional prop on every call site. */
export type OnRef = ((ref: string) => void) | undefined;

/** Past this a reference is stating its length rather than identifying a row.
 *  Message ids run to sixty characters; a transaction reference is eight. */
const MAX_SHOWN = 24;

/** One reference, as a control.
 *
 *  A span with a button role, not a `<button>`: the styling is the same token
 *  the evidence tables print (`.ref`), so a reference in a sentence and a
 *  reference in a column read as one object, and a real button would arrive
 *  carrying the agent stylesheet's own font and padding.
 */
export function Ref({ value, onRef, title }: {
  value: string;
  onRef?: OnRef;
  title?: string;
}) {
  const shown = value.length > MAX_SHOWN
    ? `${value.slice(0, MAX_SHOWN - 1)}…` : value;

  if (!onRef) return <span className="ref mono" title={value}>{shown}</span>;

  const open = () => onRef(normaliseRef(value));
  return (
    <span
      className="ref mono ref-link"
      role="button"
      tabIndex={0}
      title={title ? `${value} — ${title}` : value}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      }}
    >
      {shown}
    </span>
  );
}

/** A line of engine text with its references turned into controls.
 *
 *  The text goes in as text. Engine prose carries merchant descriptors copied
 *  verbatim from the statement (`PP*ZTRDNG LLC 8552`), so it never reaches a
 *  markdown parser — see `lib/markdown.ts`. Splitting on the pattern is the
 *  whole markup this path gets.
 */
export function RefText({ text, pattern, onRef, title }: {
  text: string;
  pattern: RegExp | null;
  onRef?: OnRef;
  title?: string;
}) {
  if (!pattern || !onRef || !text) return <>{text}</>;

  pattern.lastIndex = 0;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
    if (match.index > cursor) parts.push(text.slice(cursor, match.index));
    parts.push(
      <Ref key={`${match.index}-${match[0]}`} value={match[0]} onRef={onRef}
           title={title} />,
    );
    cursor = match.index + match[0].length;
  }
  if (!parts.length) return <>{text}</>;
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}
