/** The engine's line grammar, read back.
 *
 *  When no model is reachable — or when a model reply cited a figure the tool
 *  result does not contain — the backend answers from `app/llm/summarize.py`
 *  instead. That text is not markdown and is never parsed as markdown (see
 *  `lib/markdown.ts`): it is a small fixed grammar, written the same way in
 *  every language because the wording lives in the i18n catalog and only the
 *  punctuation is in the code.
 *
 *      • [Needs your confirmation] Charged twice by Chegg
 *        Two charges of $14.95 on the same day.
 *        Dispute deadline 2026-09-04 — 14 days left.
 *        Sources: Statement:ACC-0142, Card:CRD-0031
 *        → Check whether you were billed twice.
 *
 *  A bullet is the item, two-space continuation lines are its parts, and
 *  `→` opens the next step. Reading it back lets the chat pane draw a bullet
 *  that carries a verdict as the same card the evidence panel shows, rather
 *  than as five lines of flattened text.
 */

import type { Finding, Source } from "./types";

export interface EngineItem {
  /** The verdict in square brackets, printed in the user's language. */
  label: string | null;
  title: string;
  detail: string | null;
  /** Everything else the bullet carried, in the order it was written — the
   *  dispute deadline among it, which `Message.tsx` re-colours by matching it
   *  against the findings in the tool result. */
  meta: string[];
  /** The source list, prefix stripped. Parsed by `parseSources`. */
  sources: string | null;
  next: string | null;
}

export type EngineBlock =
  | { kind: "para"; lines: string[] }
  | { kind: "bullets"; items: EngineItem[] };

/** `• ` — the one bullet the engine writes. Matched after trimming, because
 *  `explain_charge` indents a whole nested finding block by two spaces. */
const BULLET = /^•\s+(.*)$/;
/** `[Needs your confirmation] title` */
const LABELLED = /^\[([^\]]+)\]\s*(.*)$/;
/** `→ next step` */
const NEXT = /^→\s*(.*)$/;
/** `Sources: …` / `Nguồn: …` — `common.sources_line` in both catalogs. */
const SOURCES = /^(?:Sources|Nguồn)\s*:\s*(.*)$/;

function emptyItem(title: string, label: string | null): EngineItem {
  return { label, title, detail: null, meta: [], sources: null, next: null };
}

/** Split the engine's answer into paragraphs and runs of bullets. */
export function parseEngineText(text: string): EngineBlock[] {
  const blocks: EngineBlock[] = [];
  let para: string[] | null = null;
  let items: EngineItem[] | null = null;

  const closeAll = () => {
    if (para?.length) blocks.push({ kind: "para", lines: para });
    if (items?.length) blocks.push({ kind: "bullets", items });
    para = null;
    items = null;
  };

  for (const raw of (text ?? "").split("\n")) {
    const line = raw.trim();
    if (!line) {                                  // blank line ends the block
      closeAll();
      continue;
    }

    const bullet = BULLET.exec(line);
    if (bullet) {
      if (para?.length) {                         // prose, then its bullets
        blocks.push({ kind: "para", lines: para });
        para = null;
      }
      const labelled = LABELLED.exec(bullet[1]);
      const item = labelled
        ? emptyItem(labelled[2], labelled[1])
        : emptyItem(bullet[1], null);
      if (items) items.push(item);
      else items = [item];
      continue;
    }

    // An indented line belongs to the bullet above it. Indentation is the only
    // signal: a continuation can otherwise look like any sentence.
    const indented = raw.startsWith("  ") && items?.length;
    if (indented) {
      const item = items![items!.length - 1];
      const next = NEXT.exec(line);
      if (next) { item.next = next[1]; continue; }
      const sources = SOURCES.exec(line);
      if (sources) { item.sources = sources[1]; continue; }
      if (item.detail === null) item.detail = line;
      else item.meta.push(line);
      continue;
    }

    if (items?.length) {                          // bullets, then more prose
      blocks.push({ kind: "bullets", items });
      items = null;
    }
    if (para) para.push(line);
    else para = [line];
  }

  closeAll();
  return blocks;
}

/** `Statement:ACC-0142, Card:CRD-0031` -> the kind and the reference.
 *
 *  Only the two fields the chip shows. The full source — with the detail text
 *  behind it — is on the finding in the tool result, and a bullet that has one
 *  is drawn from that instead of from this line.
 */
export function parseSources(line: string): { kind: string | null; ref: string }[] {
  const out: { kind: string | null; ref: string }[] = [];
  for (const chunk of line.split(",")) {
    const entry = chunk.trim();
    if (!entry) continue;
    const split = entry.indexOf(":");
    // Angle brackets come off the same way the evidence chips take them off:
    // a message id is written `<…>` in the mailbox and bare in the panel.
    const strip = (value: string) => value.replace(/^<|>$/g, "");
    if (split === -1) out.push({ kind: null, ref: strip(entry) });
    else {
      out.push({
        kind: entry.slice(0, split).trim() || null,
        ref: strip(entry.slice(split + 1).trim()),
      });
    }
  }
  return out;
}

/* -------------------------------------------------- findings in the result */

/** The fields a rendered finding always has (`engine/render.py`). Checked
 *  rather than read from a known key: the fourteen tools put findings under
 *  `findings`, `price_increases`, `new`, and `matches[].findings`, and a list
 *  of key names would go stale the first time a tool grew a field. */
function isFinding(value: unknown): value is Finding {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return typeof row.id === "string"
    && typeof row.title === "string"
    && typeof row.label === "string"
    && typeof row.label_text === "string"
    && Array.isArray(row.txn_ids);
}

const MAX_DEPTH = 8;

/** Every finding the tool result carries, deduplicated by fingerprint. */
export function collectFindings(data: unknown): Finding[] {
  const seen = new Set<string>();
  const out: Finding[] = [];

  function walk(node: unknown, depth: number): void {
    if (depth > MAX_DEPTH || node === null || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const item of node) walk(item, depth + 1);
      return;
    }
    if (isFinding(node)) {
      if (!seen.has(node.id)) {
        seen.add(node.id);
        out.push(node);
      }
      // A finding holds no other finding, so there is nothing below it.
      return;
    }
    for (const value of Object.values(node as Record<string, unknown>)) {
      walk(value, depth + 1);
    }
  }

  walk(data, 0);
  return out;
}

/** The finding a bullet was rendered from, if the tool result still holds it.
 *
 *  Matched on the two things the bullet prints — its verdict and its title —
 *  and on the title alone when the bullet carried no verdict, which is how
 *  `get_overview`'s preview writes them. Nothing is matched on position: the
 *  engine truncates its lists, so the sixth bullet is not the sixth finding.
 */
export function findingFor(item: EngineItem,
                           findings: Finding[]): Finding | null {
  if (!item.title) return null;
  const title = item.title.trim();
  const exact = findings.find(
    (finding) => finding.title.trim() === title
      && (!item.label || finding.label_text.trim() === item.label.trim()),
  );
  if (exact) return exact;
  return findings.find((finding) => finding.title.trim() === title) ?? null;
}

/** Re-export so a consumer drawing source chips from either path — the parsed
 *  line or the tool result — has one name for the shape it is holding. */
export type { Source };
