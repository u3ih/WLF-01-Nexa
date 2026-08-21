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
  /** Handed the turns the answer landed in, so the caller never has to read
   *  them back out of a state update that may not have committed yet. */
  onReply: (reply: ChatReply, turns: Turn[]) => void;
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
  // The thread as it stands right now. ask() runs across an await and the
  // handle is callable from outside, so neither can rely on the `turns` a
  // render happened to capture.
  const turnsRef = useRef<Turn[]>([]);
  // A language the user asked for ("từ giờ trả lời bằng tiếng Anh"). The chat
  // endpoint holds no session, so the request only survives the turn if it is
  // remembered here and sent back with everything that follows. A ref, not
  // state: ask() reads it across an await and from outside this render.
  const replyLang = useRef<Lang | null>(null);
  // Bumped every time the thread is replaced — a new chat, or another session
  // opened. An answer that arrives after that was asked in a conversation the
  // user has left: showing it would put it under the wrong thread, and the
  // save that follows would write that thread over the session it came from.
  const epoch = useRef(0);

  /** Every change to the thread goes through here, so the ref and the state
   *  can never disagree about what the conversation currently holds. */
  function applyTurns(next: Turn[]) {
    turnsRef.current = next;
    setTurns(next);
  }

  /** Replaces the thread: the answer to anything still in flight is dropped
   *  rather than landing in whatever is on screen by then. */
  function replaceThread(next: Turn[]) {
    epoch.current += 1;
    // The language request belonged to the conversation being left.
    replyLang.current = null;
    applyTurns(next);
    setError(null);
    // The request that was pending belongs to the previous thread and can no
    // longer report anything here, so the composer must not stay disabled.
    busyRef.current = false;
    setBusy(false);
  }

  useEffect(() => {
    // Not on the empty state: scrolling to the bottom there would push the
    // greeting and the suggestion cards off the top of the screen.
    if (turns.length === 0) return;
    threadRef.current?.scrollTo({
      top: threadRef.current.scrollHeight, behavior: "smooth",
    });
  }, [turns, busy]);

  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);

  // Using the toggle is itself a language choice, and the newer one wins: a
  // request made three questions ago must not override the switch just made.
  useEffect(() => { replyLang.current = null; }, [lang]);

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
    // Which conversation this question is being asked in. Checked again on the
    // way back: everything below only applies if it is still the open one.
    const asked = epoch.current;
    setError(null);
    setDraft("");
    applyTurns([...turnsRef.current, { role: "user", text }]);
    setBusy(true);
    try {
      const reply = await api.chat(text, lang, replyLang.current);
      if (asked !== epoch.current) return;
      // Null means nobody has asked for a language yet, so a turn that carries
      // nothing must not erase a request made earlier.
      if (reply.reply_lang) replyLang.current = reply.reply_lang;
      const next: Turn[] = [
        ...turnsRef.current,
        { role: "assistant", text: reply.answer, reply },
      ];
      applyTurns(next);
      onReply(reply, next);
    } catch (exception) {
      if (asked !== epoch.current) return;
      setError(exception instanceof Error ? exception.message : String(exception));
    } finally {
      // Only the request the composer is actually waiting on may release it:
      // a stale one finishing would clear the spinner of the question the user
      // has since asked in the conversation they moved to.
      if (asked === epoch.current) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  /** Drops the answer and re-sends the question above it, so "ask again" leaves
   *  one exchange rather than stacking a near-duplicate underneath. */
  function retry(index: number) {
    const question = turnsRef.current[index - 1];
    if (!question || question.role !== "user" || busyRef.current) return;
    // Not a thread replacement: this is the same conversation, so the epoch
    // stays put and the answer to the re-sent question is still welcome.
    applyTurns(turnsRef.current.slice(0, index - 1));
    ask(question.text);
  }

  useImperativeHandle(ref, () => ({
    ask,
    reset: () => {
      replaceThread([]);
      setDraft("");
    },
    // A stored session may predate a field, so treat a missing list as empty
    // rather than letting the thread render over undefined.
    loadTurns: (newTurns: Turn[]) => replaceThread(newTurns ?? []),
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
