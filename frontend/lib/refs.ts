/** Transaction references, and which evidence view holds the row behind one.
 *
 *  A reference in an answer is a control, never a link: clicking it opens the
 *  panel beside the conversation and scrolls to the row. Nothing here touches
 *  the network, and only references the tool result actually contains become
 *  controls — a reference the model mistyped stays inert text, which is the
 *  same guarantee the backend's grounding check makes on figures.
 */

import type { Element, ElementContent, Root, RootContent } from "hast";

/* ------------------------------------------------------------------ views */

/** The nine data views in the evidence panel. `boundaries` is not here: it
 *  describes the code rather than the dataset, so no row can point at it. */
export type EvidenceView =
  | "findings" | "cashflow" | "report" | "subs" | "email" | "tri"
  | "reminders" | "journal" | "statement";

export interface RefFocus {
  ref: string;
  view: EvidenceView;
  /** Bumped on every click. Clicking the same reference twice has to re-run
   *  the scroll, and without this the state would be identical and React
   *  would drop the second click. */
  seq: number;
}

/** Which view lists the rows a tool read. Keyed on the tool the reply names,
 *  so the panel that opens is the one holding the evidence for that answer. */
const TOOL_VIEW: Record<string, EvidenceView> = {
  get_overview: "findings",
  get_findings: "findings",
  run_monitor_scan: "reminders",
  get_reminders: "reminders",
  get_cashflow: "cashflow",
  get_report: "report",
  draft_report_email: "report",
  list_subscriptions: "subs",
  get_cancellation_guide: "subs",
  get_email_recon: "email",
  get_tri_source: "tri",
  get_audit_log: "journal",
  explain_charge: "statement",
  search_transactions: "statement",
};

/** Findings is the fallback: it is the view every reply has something in, and
 *  an answer with no tool behind it (smalltalk, a hard refusal) has no rows. */
export function viewForTool(tool: string | null | undefined): EvidenceView {
  return (tool && TOOL_VIEW[tool]) || "findings";
}

/* ------------------------------------------------------- finding the refs */

/** How the dataset writes a reference: `ACC-0142`, `CRD-0007`. */
const REF_SHAPE = /\b(?:ACC|CRD)-\d{3,5}\b/gi;

/** Case-folded to the form the dataset uses, so the panel's `data-ref` lookup
 *  still finds the row when a model prints the reference in lower case.
 *  Anything that is not a transaction reference — a message id, say — is left
 *  exactly as it came, because those are matched verbatim. */
export function normaliseRef(value: string): string {
  return /^(?:acc|crd)-\d{3,5}$/i.test(value) ? value.toUpperCase() : value;
}

/** How deep to walk a tool result. Deep enough for the nested shapes the
 *  tools return (`matches[].findings[].sources[]`), shallow enough that a
 *  self-referential payload cannot spin. */
const MAX_DEPTH = 8;

/** Every reference the tool result mentions, wherever it sits in the payload.
 *
 *  Walked rather than read from known keys on purpose: the fourteen tools put
 *  references under `ref`, `txn_ids`, `matched_txn_ref`, `card_ref` and inside
 *  free text such as a report's `[CRD-0031]`, and a list of key names would go
 *  stale the first time a tool grew a field.
 */
export function collectRefs(data: unknown): string[] {
  const found = new Set<string>();

  function walk(node: unknown, depth: number): void {
    if (depth > MAX_DEPTH || node === null || node === undefined) return;
    if (typeof node === "string") {
      for (const match of node.matchAll(REF_SHAPE)) {
        found.add(normaliseRef(match[0]));
      }
      return;
    }
    if (Array.isArray(node)) {
      for (const item of node) walk(item, depth + 1);
      return;
    }
    if (typeof node === "object") {
      for (const value of Object.values(node as Record<string, unknown>)) {
        walk(value, depth + 1);
      }
    }
  }

  walk(data, 0);
  return [...found];
}

const ESCAPE = /[.*+?^${}()|[\]\\]/g;

/** One pattern matching any of these references and nothing else.
 *
 *  Longest first: `ACC-1` must not match inside `ACC-1042` and leave a stray
 *  digit behind. Case-insensitive to catch a model that lower-cased one;
 *  `normaliseRef` puts it back before the panel looks the row up.
 */
export function refPattern(refs: string[]): RegExp | null {
  if (!refs.length) return null;
  const alternatives = [...refs]
    .sort((a, b) => b.length - a.length)
    .map((ref) => ref.replace(ESCAPE, "\\$&"))
    .join("|");
  return new RegExp(`(?:${alternatives})`, "gi");
}

/* --------------------------------------------------------- markdown markup */

/** Elements whose text is quoted verbatim. A reference inside a code span is
 *  being shown, not cited, and turning it into a control would rewrite it. */
const VERBATIM = new Set(["code", "pre", "kbd", "samp"]);

/** Split one text value on the references it contains. */
function splitOnRefs(value: string, pattern: RegExp): ElementContent[] | null {
  pattern.lastIndex = 0;
  const parts: ElementContent[] = [];
  let cursor = 0;
  for (let match = pattern.exec(value); match; match = pattern.exec(value)) {
    if (match.index > cursor) {
      parts.push({ type: "text", value: value.slice(cursor, match.index) });
    }
    parts.push({
      type: "element",
      tagName: "span",
      properties: { dataRef: match[0] },
      children: [{ type: "text", value: match[0] }],
    } satisfies Element);
    cursor = match.index + match[0].length;
  }
  if (!parts.length) return null;
  if (cursor < value.length) {
    parts.push({ type: "text", value: value.slice(cursor) });
  }
  return parts;
}

/** A rehype plugin that marks the references in model prose.
 *
 *  Marking, not linking: it emits `<span data-ref="…">`, and the markdown
 *  component map in `components/Message.tsx` turns that into the control. A
 *  null pattern — a reply whose tool returned no references — leaves the tree
 *  untouched, so nothing in the prose becomes clickable.
 */
export function rehypeRefs(pattern: RegExp | null) {
  return function transform(tree: Root): void {
    if (!pattern) return;
    const active = pattern;

    function visit(parent: Root | Element): void {
      const children: RootContent[] = [];
      let changed = false;
      for (const child of parent.children as RootContent[]) {
        if (child.type === "text") {
          const parts = splitOnRefs(child.value, active);
          if (parts) {
            children.push(...(parts as RootContent[]));
            changed = true;
            continue;
          }
        } else if (child.type === "element") {
          // Already a marked reference: recursing would mark its own text.
          if (!VERBATIM.has(child.tagName) && !child.properties?.dataRef) {
            visit(child);
          }
        }
        children.push(child);
      }
      if (changed) parent.children = children as typeof parent.children;
    }

    visit(tree);
  };
}
