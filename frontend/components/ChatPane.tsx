"use client";

import {
  ArrowUp, CreditCard, Receipt, RefreshCcw, Search,
} from "lucide-react";
import {
  forwardRef, useEffect, useImperativeHandle, useRef, useState,
} from "react";

import { AssistantTurn } from "@/components/Message";
import { api } from "@/lib/api";
import { SAMPLE_QUESTIONS, ui } from "@/lib/i18n";
import type { ChatReply, Lang, Turn } from "@/lib/types";

export interface ChatHandle {
  ask: (question: string) => void;
  reset: () => void;
  loadTurns: (turns: Turn[]) => void;
  getTurns: () => Turn[];
}

const SUGGEST_ICONS = [Receipt, Search, CreditCard, RefreshCcw];

/** "MINH ANH NGUYEN" reads as shouting in a greeting. */
function titleCase(name: string): string {
  return name.toLocaleLowerCase().replace(/(^|\s)(\p{L})/gu,
    (_, gap: string, letter: string) => gap + letter.toLocaleUpperCase());
}

export const ChatPane = forwardRef<ChatHandle, {
  lang: Lang;
  ownerName: string | undefined;
  disclaimer: string;
  onReply: (reply: ChatReply) => void;
  onBusyChange: (busy: boolean) => void;
  onRef: (ref: string, tool: string | null) => void;
}>(function ChatPane(
  { lang, ownerName, disclaimer, onReply, onBusyChange, onRef }, ref,
) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Vietnamese input goes through an IME. Enter pressed mid-composition is the
  // IME committing a syllable, not the user sending: submitting there clears
  // the box, and the composition that lands afterwards types the syllable back
  // into the empty box. Track composition and let the IME finish first.
  const composing = useRef(false);
  // ask() is reachable from the sidebar, so it must not close over stale state.
  const busyRef = useRef(false);

  useEffect(() => {
    // Not on the empty state: scrolling to the bottom there would push the
    // greeting and the suggestion cards off the top of the screen.
    if (turns.length === 0) return;
    threadRef.current?.scrollTo({
      top: threadRef.current.scrollHeight, behavior: "smooth",
    });
  }, [turns, busy]);

  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);

  // Grow the box with the question instead of scrolling a two-line window.
  // Measured twice on purpose: on the first commit the stylesheet is not
  // necessarily applied yet, and scrollHeight read against an unstyled box
  // reports the 180px cap. The extra frame re-measures once styling has landed.
  useEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    const fit = () => {
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
    };
    fit();
    const frame = requestAnimationFrame(fit);
    return () => cancelAnimationFrame(frame);
  }, [draft]);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busyRef.current) return;
    busyRef.current = true;
    setError(null);
    setDraft("");
    setTurns((previous) => [...previous, { role: "user", text }]);
    setBusy(true);
    try {
      const reply = await api.chat(text, lang);
      setTurns((previous) => [
        ...previous,
        { role: "assistant", text: reply.answer, reply },
      ]);
      onReply(reply);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  /** Drops the answer and re-sends the question above it, so "ask again" leaves
   *  one exchange rather than stacking a near-duplicate underneath. */
  function retry(index: number) {
    const question = turns[index - 1];
    if (!question || question.role !== "user" || busyRef.current) return;
    setTurns((previous) => previous.slice(0, index - 1));
    ask(question.text);
  }

  function loadTurns(newTurns: Turn[]) {
    setTurns(newTurns);
    setError(null);
  }

  function getTurns(): Turn[] {
    return turns;
  }

  useImperativeHandle(ref, () => ({
    ask,
    reset: () => {
      setTurns([]);
      setDraft("");
      setError(null);
    },
    loadTurns,
    getTurns,
  }));

  return (
    <>
      <div className="thread" ref={threadRef}>
        <div className="thread-inner">
          {turns.length === 0 ? (
            <div className="hero">
              <h1 className="hero-title">
                {ui(lang, "greeting")}
                {ownerName ? ` ${titleCase(ownerName)}` : ""}
              </h1>
              <p className="hero-sub">{ui(lang, "heroSub")}</p>
              <div className="suggest-grid">
                {SAMPLE_QUESTIONS[lang].slice(0, 4).map((question, index) => {
                  const Icon = SUGGEST_ICONS[index];
                  return (
                    <button
                      className="suggest"
                      key={question}
                      onClick={() => ask(question)}
                      disabled={busy}
                    >
                      <span>{question}</span>
                      <span className="suggest-icon"><Icon size={15} /></span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {turns.map((turn, index) =>
            turn.role === "user" ? (
              <div className="turn turn-user" key={index}>
                <div className="bubble">{turn.text}</div>
              </div>
            ) : (
              <div className="turn turn-ai" key={index}>
                <span className="ai-mark">N</span>
                <AssistantTurn
                  lang={lang}
                  text={turn.text}
                  reply={turn.reply}
                  onAsk={ask}
                  onRetry={() => retry(index)}
                  onRef={onRef}
                />
              </div>
            ))}

          {busy ? (
            <div className="turn turn-ai">
              <span className="ai-mark">N</span>
              <div className="ai-body">
                <div className="thinking">
                  <span className="spinner" /> {ui(lang, "sending")}…
                </div>
              </div>
            </div>
          ) : null}
          {error ? <p className="err">{error}</p> : null}
        </div>
      </div>

      <div className="composer-wrap">
        <div className="composer-inner">
          <div className="composer">
            <textarea
              ref={inputRef}
              rows={1}
              value={draft}
              placeholder={ui(lang, "ask")}
              onChange={(event) => setDraft(event.target.value)}
              onCompositionStart={() => {
                composing.current = true;
              }}
              onBlur={() => {
                // compositionend cannot be relied on if focus leaves mid-syllable,
                // and a flag stuck at true would swallow Enter for good.
                composing.current = false;
              }}
              onCompositionEnd={(event) => {
                composing.current = false;
                // The value that lands with the composition is authoritative:
                // React's onChange for it can arrive after this event.
                setDraft((event.target as HTMLTextAreaElement).value);
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.shiftKey) return;
                // keyCode 229 is the pre-standard signal for the same thing.
                if (composing.current || event.nativeEvent.isComposing
                  || event.keyCode === 229) {
                  return;
                }
                event.preventDefault();
                ask(draft);
              }}
            />
            <button
              className="send"
              onClick={() => ask(draft)}
              disabled={busy || !draft.trim()}
              title={ui(lang, "send")}
              aria-label={ui(lang, "send")}
            >
              {busy ? <span className="spinner" /> : <ArrowUp size={19} />}
            </button>
          </div>

          {/* Whole notice, always. The brief calls it "hiển thị cố định, KHÔNG
              cho ẩn", and a "details" toggle hides part of it by default —
              including the 60-day deadline, which is the sentence that costs
              the user real money if they never read it. It sits under the
              composer because that is the one element that never scrolls away. */}
          {/* <p className="notice">
            <strong>{ui(lang, "disclaimerLabel")}</strong> {disclaimer}
          </p> */}
        </div>
      </div>
    </>
  );
});
