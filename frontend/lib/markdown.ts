/** Answers arrive from two authors that need opposite treatment.
 *
 *  The engine writes plain text: "• " bullets, two-space continuation lines,
 *  and merchant descriptors copied verbatim from the statement. Descriptors
 *  contain asterisks — `PP*ZTRDNG LLC 8552`, `AMZN MKTP US*2K91` — and two of
 *  them in one paragraph would pair up into emphasis and silently rewrite the
 *  descriptor. In a tool whose job is showing the exact descriptor, that is a
 *  correctness bug, so engine text has its emphasis characters escaped and only
 *  the bullets converted.
 *
 *  The model writes markdown on purpose. Its text is passed through untouched.
 */

const MODEL_SOURCES = new Set(["llm", "llm_retry"]);

export function isModelAuthored(source: string | undefined): boolean {
  return source !== undefined && MODEL_SOURCES.has(source);
}

export function toMarkdown(text: string, source: string | undefined): string {
  if (isModelAuthored(source)) return text;
  return text
    .replace(/([*_`~])/g, "\\$1")
    .replace(/^(\s*)•[ \t]+/gm, "$1- ");
}
