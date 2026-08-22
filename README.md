# WLF-01-Nexa

# Nexa — Wealify statement review assistant (WLF-01)

A bilingual (Tiếng Việt / English) chat assistant that reads a Wealify **sample**
account statement, the sample mailbox, the wallet ledger and the card statement,
then points out what deserves a second look: forgotten subscriptions, double
charges, duplicated fees, money that left the account but never reached the card,
silent price rises, and receipts that do not exist.

It is **read-only with money**. It cannot cancel a plan, open a dispute, move
funds or lock a card — there is no code path that does any of those. It only ever
emails **you**, and only after you confirm a specific draft.

> Công cụ này chỉ hỗ trợ bạn rà soát tài chính. Kết quả để tham khảo, không phải
> kết luận chính thức của Wealify và không thay cho việc bạn tự kiểm tra. Nếu thấy
> giao dịch lạ, hãy liên hệ hỗ trợ ngay — ở Mỹ thời hạn khiếu nại là 60 ngày kể từ
> ngày ngân hàng gửi sao kê.

---

## Run it in 10 minutes

Requirements: **Python 3.10+**, **Node 22.12+**, **Docker** (for Postgres).
An LLM is optional — see *Which model, and where it runs* below.

```bash
git clone <this-repo> && cd WLF-01-Nexa
make setup      # venv + pip, npm install, starts Postgres, generates sample data
make import-dataset # apply migrations and import dataset/*.csv into Postgres
make dev        # backend on :8000, frontend on :3000
```

Open **http://localhost:3000**. API docs are at http://localhost:8000/docs.

Everything in Docker instead (one command, no local Python/Node needed):

```bash
make deploy     # builds postgres + backend + frontend, then runs the smoke test
make deploy-down
```

Verify it does what it claims:

```bash
make test       # 86 tests: engine vs answer key, guardrails, de-duplication, masking
make smoke      # curls the running stack and checks the safety rules
```

---

## What to try first

Click the sample buttons in the UI, or type:

| Question | What it exercises |
|---|---|
| *Tháng này tôi chi bao nhiêu, phí bao nhiêu, 3 khoản lớn nhất là gì?* | month/quarter/year report |
| *Khoản $9.99 này là gì — có email xác nhận nào khớp không?* | descriptor explanation + email match |
| *Có tiền nào rời tài khoản mà chưa thấy lên thẻ không?* | account ↔ wallet ↔ card reconciliation |
| *Mình đang có những gói đăng ký định kỳ nào, gói nào vừa tăng giá?* | recurrence, next charge, silent price rise |
| *Có khoản nào bị tính hai lần / phí kép không?* | duplicate charge, duplicated fee, duplicate deposit |
| *Gửi báo cáo tháng này vào email của tôi.* | draft → your confirmation → send to **your** address |

The three trap questions are wired to buttons too, so a judge can see the refusals:
*"Tự huỷ mấy gói không dùng đi"*, *"Gửi email khiếu nại cho Netflix giúp tôi"*,
*"Tài khoản mình có an toàn không?"*

## What it finds in the sample data

15 findings, each with one of three labels, its sources, and a 60-day dispute
deadline: 5 recurring plans, a Chegg subscription still charging with no receipt
for 7 cycles, a Netflix rise from $15.49 to $17.99, a $6.75 charge duplicated 94
seconds apart, a $25 wire fee charged twice in one day, a $1,200 deposit posted
twice, a $500 transfer with no matching card load, a $38.40 wallet gap, an
unidentifiable `PP*ZTRDNG LLC 8552`, a $248.13 charge with no receipt anywhere,
and a look-alike "Netflix" email from `netfl1x-billing.com`.

Four near-miss transactions are planted as well (same amount hours apart, same
amount 46 days apart, a two-charge merchant, a different fee on the same day).
`make test` asserts none of them is flagged, so over-flagging fails the suite.

---

## Safety, enforced in code rather than in a prompt

| Rule | How it is guaranteed |
|---|---|
| No action on money | No cancel / dispute / transfer / freeze function exists anywhere. The model's whole capability surface is 14 read-only tools. |
| Email destination | `POST /api/report/send` ignores request recipients and sends only to `NEXA_MAIL_TO`, then requires a single-use confirmation token. |
| Third-party letters | Produced as drafts for you to send. There is no sending code path for them. |
| No invented figures | The engine computes every number; the model only narrates. Any amount, ₫ figure or transaction reference in a reply that is absent from the tool result is rejected, retried once, then replaced by the engine's own wording. |
| No blanket reassurance | Replies are filtered for "your account is safe", "nothing unusual", "the bank is investigating" and similar, in both languages. |
| Masking | Card numbers appear only as `•••• 4821`, accounts as `••••••6390`. No model in the codebase has a CVV field, so it cannot be stored. |
| No repeat alerts | Each finding has a fingerprint with a unique constraint in Postgres; a re-scan returns only what is new and reports how many repeats it suppressed. |
| Auditability | Every flag is journaled with its reason and confidence, exportable as CSV or JSON. |

## Which model, and where it runs

The provider is a matter of configuration, not of code. Two transports ship, and
`.env` alone decides:

| `NEXA_AI_PROVIDER` | Talks to | Config |
|---|---|---|
| `ollama` | A local Ollama daemon | `NEXA_AI_URL=http://localhost:11434` |
| `openai` | Any OpenAI-compatible API — BytePlus Ark, OpenAI, Groq, Together, vLLM, llama.cpp's server | `NEXA_AI_URL=https://…/v1` (or `/api/v3`) + `NEXA_AI_API_KEY` |
| `auto` *(default)* | Decides from the URL shape and whether a key is set, then confirms by probing the other one | — |

The key is read from the environment only; `.env` is git-ignored and no key is
logged, returned by the API or sent to the browser.

On top of that the assistant picks the best available tier at startup and says
which one it used under every answer:

1. **native tools** — the model advertises, or accepts, tool calling
   (e.g. `ollama pull qwen3:8b`, or most hosted endpoints). If an endpoint
   rejects the tool schema, the tier drops to the JSON router by itself.
2. **JSON router** — any chat model; it returns `{"tool": …, "args": …}`.
3. **engine only** — no model reachable, or `NEXA_OFFLINE_MODE=true`. The
   assistant still answers, in both languages, from the deterministic engine.

`GET /api/health` reports the provider, the model, the tier and — when the model
is down — why, in a sentence you can act on (bad key, wrong base path, model not
listed).

Running the stack in Docker against a **local** Ollama? A container cannot reach
an Ollama bound to localhost, so start it as `OLLAMA_HOST=0.0.0.0 ollama serve`.
A hosted endpoint needs nothing extra. Without either the deployed stack still
answers — from the engine.

Routing is keyword-first and model-second: for the phrasings this dataset is
built around the keyword table is exact and free, so a turn usually costs one
model call, used purely for wording.

## Money units

Amounts are held internally as integer cents so totals are exact, and published
as dollars. Vietnamese answers lead with đồng and keep the exact USD figure in
brackets — `≈519.000 ₫ ($19.95)`. The statement is denominated in USD, so the ₫
value is a **reference conversion**, never presented as a bank rate.

The USD→VND rate is fetched daily alongside the ECB rates — the ECB publishes no
đồng quote, so it comes from a separate publication and is labelled with its
source and publication date wherever a ₫ figure appears. `NEXA_USD_VND_RATE`
(default 26.000) is the fallback for a machine that has never reached that
publication; when it is in use the note says so instead of naming a date. Both
the rate and its basis are shown in the UI footer, on `/api/health` and in full
on `/api/fx`.

## Configuration

Copy `.env.example` to `.env` (setup does this for you). Nothing secret is
committed and `.env` is git-ignored. Confirmed report emails are sent through
SMTP only; outbox delivery is disabled and a missing SMTP host returns an error
instead of writing `backend/outbox/*.eml`.

```bash
NEXA_MAIL_MODE=smtp
NEXA_MAIL_TO=vaithieu0605@gmail.com
NEXA_SMTP_HOST=smtp.example.com
NEXA_SMTP_PORT=587
NEXA_SMTP_USER=nexa@example.com
NEXA_SMTP_PASSWORD=...
NEXA_SMTP_FROM=nexa@example.com
NEXA_SMTP_STARTTLS=true
```

Use `POST /api/report/smtp-test` to send a small test email to `NEXA_MAIL_TO`
before sending a report.

## Deploy backend on Railway and frontend on Vercel

Railway must build from the repository root because `backend/Dockerfile` copies
the shared `dataset/`, `migrations/` and scraper directories. Leave Railway's
**Root Directory empty**; `railway.json` selects `backend/Dockerfile` and adds
the `/api/health` deployment healthcheck.

Add a Railway Postgres service and set the backend variable to Railway's
reference variable instead of localhost:

```env
NEXA_DATABASE_URL=${{Postgres.DATABASE_URL}}
```

Add the remaining `NEXA_*` variables from `.env.example`, then generate a public
Railway domain for the backend. Do not copy the local `localhost:55432` database
URL into Railway.

On Vercel, import the same repository and set **Root Directory** to `frontend`.
Add this server-side environment variable for Production and Preview, replacing
the example with the Railway public domain (without a trailing slash):

```env
BACKEND_URL=https://your-backend.up.railway.app
```

Do not set `NEXT_PUBLIC_API_BASE`. The browser calls same-origin `/api/*`, and
the Next.js rewrite proxies those requests to Railway. This also avoids exposing
backend configuration in the client bundle and does not require production CORS.

## After the contest

```bash
make purge      # deletes sample data, outbox, logs and all Postgres state
```

## Layout

```
backend/
  app/engine/    loaders, classification, recurrence, anomalies, email match,
                 3-source reconciliation, reports, labels, journal  (pure Python)
  app/llm/       tools (read-only), prompts, guardrails, model client
                 (Ollama + OpenAI-compatible), chat loop
  app/routers/   FastAPI endpoints;  app/store.py  Postgres state
  app/db/        versioned migration runner
  migrations/    SQL schema for application state and dataset tables
  data/import_dataset.py  idempotent CSV → Postgres importer
  data/generate.py   the synthetic dataset AND its answer key
  tests/         ground truth, guardrails, de-duplication, masking, opt-in LLM
frontend/        Next.js 16 chat + evidence tabs ("Ledger Ink" theme)
scripts/         setup.sh  run.sh  deploy.sh  smoke.sh  purge.sh
docs/DESIGN.md   detection rules, answer key, safety matrix, architecture
```

All data in this repository is synthetic and generated by `data/generate.py`.
No real person, card or account is involved.

## Importing the CSV export into Postgres

The versioned schema is in `migrations/001_initial_schema.sql`. Apply it and
import the current export with:

```bash
make migrate
./scripts/import_dataset.sh --mailbox tester
```

The importer is safe to rerun: entity and ledger tables use upserts keyed by
their natural identifiers. Each run gets a `dataset_imports` batch and keeps
all source rows in `dataset_rows` for provenance. The normalized tables are:

`cards`, `virtual_accounts`, `wallets`, `financial_transactions`,
`wallet_events`, `emails`, `email_amounts`, `email_links`, and `email_codes`.
`transactions_va.csv` is marked as a stale duplicate in `dataset_files` and
stored only in `dataset_rows`, so it cannot double-count the canonical ledger.

To import another mailbox selection, rerun the command with `--mailbox senior`
or `--mailbox junior`. New records can then be inserted into the normalized
tables using the same identifiers and minor-unit money columns.
