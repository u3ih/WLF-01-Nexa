# Nexa — design notes (WLF-01)

Companion to the README: the detection rules, the answer key, the safety matrix
and the theme rationale. Useful for the slide deck and the video script.

## 1. Architecture

```
        ┌──────────────────────────── frontend (Next.js 16) ───────────────────┐
        │  chat pane            │  evidence tabs                              │
        │  · provenance chip    │  alerts · cash flow · email match ·          │
        │  · trap buttons       │  3 sources · subscriptions · reports ·       │
        │  · fixed disclaimer   │  reminders · journal · statement             │
        └───────────────┬───────────────────────────────────────────┬──────────┘
                        │  /api/* (same origin, proxied)            │
        ┌───────────────▼───────────────────────────────────────────▼──────────┐
        │ FastAPI                                                              │
        │  guardrails (pre)  →  keyword/model router  →  14 READ-ONLY tools    │
        │                                   ↓                                  │
        │  deterministic engine  ──────────────────────────►  rendered answer   │
        │   loader → classify → merchants → subscriptions → anomaly            │
        │          → email_match → tri_source → labels → reports              │
        │                                   ↓                                  │
        │  guardrails (post): banned wording, grounding of every figure & ref  │
        └───────────────┬──────────────────────────────────────────────────────┘
                        │
        ┌───────────────▼─────────┐        ┌──────────────────────────────────┐
        │ Postgres                │        │ model: Ollama, or any            │
        │ flags · journal ·       │        │ OpenAI-compatible endpoint       │
        │ reminders · drafts      │        │ tier 1 native tools              │
        │ (never money)           │        │ tier 2 JSON router               │
        │                         │        │ tier 3 not needed — engine only  │
        └─────────────────────────┘        └──────────────────────────────────┘
```

Files: `backend/app/engine/*` is pure Python with no web or model dependency, so
every graded number is unit-testable. `backend/app/llm/tools.py` is the model's
entire capability surface.

## 2. Detection rules

| Finding | Rule |
|---|---|
| Recurring subscription | ≥3 charges at one merchant, median gap 26–35 days (or 6–8 / 85–95 / 350–380), interval standard deviation ≤ 4 days. Grouping is by resolved merchant, not by amount, so a price change does not split the series. |
| Next charge | Same day-of-month one month on (not "+median days"), clamped to month length. |
| Silent price rise | Consecutive charges differ; reports old → new, %, effective date, extra cost per year, and whether the merchant's own notice email exists. |
| Forgotten subscription | Recurring, and the trailing ≥3 charges have no matching receipt in the mailbox. |
| Duplicate charge | Same merchant, same amount, ≤15 minutes apart. |
| Duplicated fee | Same fee descriptor, same amount, same day, count > 1. |
| Duplicate deposit | Same counterparty, same amount, same day, count > 1. |
| Money not on the card | Every `transfer_to_card` must match a card load by reference, or by amount within ±3 days. |
| Wallet gap | `opening + Σ ledger events` vs the wallet's reported balance. The residual is stated; the cause is not guessed. |
| Unidentified merchant | Descriptor matches no dictionary rule. The processor prefix (`SQ *`, `PP*`) is explained if known; the seller is reported as unidentified. |
| Missing receipt | Purchase ≥ the user's own 90th-percentile purchase, with no email anywhere in the mailbox. |
| Look-alike email | Display name claims a brand whose domain does not match, or a domain within edit distance 2 of the real one, or reply-to on a different domain. Pressure wording counts only as a supporting signal, never on its own. |

Labels: recurrence is provable from the statement → **Định kỳ đã xác định**.
Anything depending on the user's intent → **Cần bạn tự xác nhận**. Anything the
data cannot settle → **Chưa đủ dữ liệu**. No fourth verdict exists in the code.

## 3. Answer key

`backend/data/generate.py` is deterministic (fixed seed, hand-authored anchors)
and writes `ground_truth.json` next to the data it generates. `make test` asserts
recall, precision, labels, references, report totals, forecast dates and the
CSV↔PDF parity against that file.

**15 expected findings** — 5 recurring plans (T-Mobile $65, Chegg $19.95,
Netflix $17.99, Spotify $11.99, iCloud+ $9.99), Chegg forgotten (7 cycles with no
receipt), Netflix $15.49→$17.99 on 2026-05-16, Blue Bottle $6.75 twice 94s apart,
wire fee $25 twice on 2026-06-25, $1,200 deposit twice on 2026-06-03, $500
transfer on 2026-07-22 with no card load, $38.40 wallet gap, `PP*ZTRDNG LLC 8552`
unidentified, `AMZN MKTP US*2K91` $248.13 with no receipt, and the
`netfl1x-billing.com` email.

**4 near-misses that must stay unflagged** — Starbucks $5.25 twice 6.5 hours
apart, Whole Foods $64.20 twice 46 days apart, Coursera charged only twice, and an
ATM fee sharing the day with the duplicated wire fee.

## 4. Safety matrix

| Threat | Mitigation | Test |
|---|---|---|
| "Cancel my plans" | No cancel code exists; refusal + cancellation steps for the user | `test_guardrails.py` |
| "Email Netflix for me" | No third-party send path; refusal + draft only | `test_guardrails.py` |
| "Am I safe?" | Refuses the framing, then shows label counts and each item | `test_guardrails.py` |
| Prompt injection ("ignore your rules") | The tool registry is the boundary, not the prompt | `test_llm.py` |
| Model invents a figure or reference | Grounding check on amounts, ₫ figures and `ACC-/CRD-` refs → retry → engine text | `test_llm.py` |
| Reassuring wording | Output filter in both languages, with our own refusal wording exempted | `test_guardrails.py` |
| Card/account leakage | Masking at the boundary; no CVV field exists | `test_masking.py` |
| Repeat alerts on a schedule | Fingerprint + unique constraint; scan returns only new items | `test_dedupe.py` |

## 5. Theme — Wealify palette

Wealify's signature orange (`#FC6508`) on their near-black / white neutrals, set
in **Manrope** — the typeface wealify.com uses. The palette follows the
operating system, with a manual override that wins in both directions; all of it
is token-driven in `frontend/app/globals.css`.

Manrope is self-hosted from `frontend/public/fonts/` (three variable subsets,
52 KB total) rather than pulled from a CDN, so the UI still needs no network on
a judge's machine. The `vietnamese` subset is included deliberately: it carries
the precomposed diacritics **and** `U+20AB`, the ₫ sign this product prints on
every figure. Without it Vietnamese text would drop to a fallback face
mid-sentence. Licensed under SIL OFL 1.1 — `public/fonts/OFL.txt`.

The mark is Nexa's own, drawn in Wealify's construction — thick monoline
strokes, round caps, the crossing stroke a shade deeper. It is **not** Wealify's
logo, and that is deliberate: this assistant tells the user, in a notice it may
not hide, that its findings are *"không phải kết luận chính thức của Wealify"*.
Wearing their logo would contradict that sentence.

Four decisions worth stating out loud:

1. **No green in the verdict palette.** Green reads as "safe, nothing to do", and
   this assistant is never allowed to imply that. *Định kỳ đã xác định* is indigo
   (known, not blessed), *Cần bạn tự xác nhận* is gold, *Chưa đủ dữ liệu* is
   slate. Rose appears only for a dispute deadline that has passed — a fact, not
   a judgement.
2. **Verdict hues are held away from the accent.** Orange sits at hue 23°, so
   gold is pushed out to 50° and rose down to 347°: a badge carrying a verdict
   can never be mistaken for something clickable. Amber, the obvious choice for
   *Cần bạn tự xác nhận*, was rejected for landing at 33–35° — close enough to
   the accent to blur against it. Every label colour clears WCAG AA (4.5:1)
   against its background in both themes.
3. **Wealify's shape language, applied by element size** the way their own site
   does it: 100px pills for controls, 20px for large surfaces, 14px for dense
   cards, headings at weight 800. Their buttons are generously padded and set at
   weight 400 at 16px; ours run at 13px, where 500 is the equivalent.
4. **Tabular figures everywhere money appears** (`font-variant-numeric: tabular-nums`,
   monospace for amounts and references), so columns align and a wrong digit is
   visible. Fonts come from the system stack, so the UI needs no network.

The mandated notice sits under the composer — the one element that never
scrolls away — has no dismiss control, and is rendered from the backend
catalog, the same string the API returns with every answer.

## 6. Known limits

- The merchant dictionary is a curated list; anything outside it is reported as
  unidentified by design rather than guessed.
- The ₫ conversion uses a rate you configure. It is labelled approximate
  everywhere and is not a bank rate.
- A small local model sometimes phrases an answer loosely. When that happens the
  grounding check replaces it with the engine's own wording, which is why some
  replies are labelled *máy phân tích trả lời trực tiếp*.
