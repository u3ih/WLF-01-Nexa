/** Which of the two authors wrote an answer.
 *
 *  The model writes markdown on purpose, so its text goes through the parser.
 *  The engine writes plain text with a line grammar of its own — "• " bullets,
 *  two-space continuation lines, merchant descriptors copied verbatim from the
 *  statement. Those descriptors contain asterisks (`PP*ZTRDNG LLC 8552`,
 *  `AMZN MKTP US*2K91`), and two of them in one paragraph would pair up into
 *  emphasis and silently rewrite the descriptor, so engine text is never parsed
 *  as markdown at all — see `lib/engineText.ts`.
 */

const MODEL_SOURCES = new Set(["llm", "llm_retry"]);

export function isModelAuthored(source: string | undefined): boolean {
  return source !== undefined && MODEL_SOURCES.has(source);
}
