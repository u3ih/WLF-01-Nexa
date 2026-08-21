# Nexa (WLF-01) — Tổng quan project & cấu trúc code

> File này là bản đồ để đọc hiểu repo: project làm gì, dữ liệu đi đường nào, file nào
> chịu trách nhiệm gì, API có những endpoint nào, và những chỗ cần biết trước khi sửa.
> Đọc kèm: [README.md](../README.md) (cách chạy), [DESIGN.md](DESIGN.md) (rule phát hiện +
> đáp án chuẩn), [Giai-ngo-nghiep-vu.md](Giai-ngo-nghiep-vu.md) (nghiệp vụ cho người
> không biết tài chính), [WLF-01_Ke_hoach_lam_viec.md](WLF-01_Ke_hoach_lam_viec.md) (đề bài
> đầy đủ + tiêu chí chấm).

---

## 1. Project là gì

**Nexa** = trợ lý chat song ngữ (VI/EN) đọc sao kê mẫu của Wealify rồi chỉ ra khoản
đáng xem lại: gói đăng ký quên huỷ, khoản bị tính hai lần, phí kép, tiền rời tài khoản
mà chưa lên thẻ, tăng giá âm thầm, giao dịch không có biên lai, email giả dạng thương hiệu.

Bài thi hackathon **WLF-01** (Cross Border AI Innovation Summit 2026, track Wealify).
Chấm **trên đáp án chuẩn** (ground truth) → độ chính xác quan trọng hơn demo đẹp.

### Nguyên tắc kiến trúc số 1

> **Phát hiện = code deterministic. LLM = diễn giải + hội thoại.**

LLM không bao giờ tự đi tìm khoản trùng/định kỳ (kết quả sẽ không ổn định giữa các lần
chạy). Engine Python tính mọi con số; model chỉ kể lại bằng lời, và lời đó bị kiểm tra
lại lần nữa trước khi ra khỏi process.

### Read-only tuyệt đối với tiền

Không tồn tại code path nào huỷ gói / mở khiếu nại / chuyển tiền / khoá thẻ. Không phải
vì system prompt dặn thế — mà vì **không có hàm nào làm được**. Toàn bộ khả năng của
model = 14 tool chỉ-đọc trong [tools.py](../backend/app/llm/tools.py).

---

## 2. Stack

| Tầng | Công nghệ |
|---|---|
| Backend | Python 3.10+, FastAPI 0.115, Pydantic 2, uvicorn |
| Engine | Pure Python (không phụ thuộc web/model) — unit-test được toàn bộ |
| State | Postgres 16 (chỉ lưu flag journal, fingerprint, reminder, draft — **không lưu tiền**) |
| LLM | Ollama local **hoặc** endpoint OpenAI-compatible (chọn theo `.env`), 3 tier tự chọn lúc startup |
| Frontend | Next.js 16, React 19, TypeScript 5.7, lucide-react, react-markdown |
| Mail | `outbox` mode → ghi file `.eml` (mặc định, không cần SMTP) hoặc SMTP thật |
| Deploy | docker-compose (postgres + backend + frontend), `make deploy` |
| Test | pytest, 177 test (`make test`; 15 skip khi không có Postgres / không bật LLM) |

---

## 3. Cây thư mục

```
WLF-01-Nexa/
├── Makefile                  # setup / dev / test / smoke / deploy / purge
├── docker-compose.yml        # postgres (:55432) + backend (:8000) + frontend (:3000)
├── .env / .env.example       # config, prefix NEXA_, .env git-ignored
├── README.md                 # chạy trong 10 phút
│
├── dataset/                  # BỘ DỮ LIỆU THẬT ĐANG DÙNG (export Wealify, CSV)
│   ├── cards.csv                    # 6 thẻ
│   ├── virtual_accounts.csv         # 7 tài khoản nhận
│   ├── transactions_card.csv        # 412 dòng — CHỨA CẢ 2 sổ (thẻ + ví)
│   ├── transactions_va.csv          # bản cũ lỗi UTF-8 → bị detect & SKIP
│   └── email_{tester,senior,junior}.csv   # 3 hộp thư
│
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, lifespan, scheduler, CORS
│   │   ├── config.py         # Settings (pydantic-settings), owner_email, today()
│   │   ├── schemas.py        # request model (chat/draft/send/scan)
│   │   ├── serialize.py      # boundary: *_cents → *_usd + chuỗi hiển thị
│   │   ├── store.py          # Postgres: schema + query (5 bảng)
│   │   ├── mailer.py         # draft → confirm → send (chỉ email chủ tài khoản)
│   │   ├── monitor.py        # run_scan(): quét lại, chỉ báo cái CHƯA từng báo
│   │   ├── i18n/{vi,en}.json # catalog câu chữ — VI/EN dùng chung params
│   │   ├── engine/           # ← TOÀN BỘ LOGIC PHÁT HIỆN (pure Python)
│   │   ├── llm/              # tool, prompt, guardrail, client, chat loop
│   │   └── routers/          # endpoint FastAPI
│   ├── data/
│   │   ├── generate.py       # sinh dataset mẫu + ĐÁP ÁN CHUẨN (deterministic seed)
│   │   └── sample/           # account_statement.{csv,pdf}, card_statement.csv,
│   │                         #   wallet_ledger.json, mailbox/*.eml, ground_truth.json
│   ├── outbox/               # *.eml báo cáo đã gửi (mail_mode=outbox)
│   └── tests/                # 177 test
│
├── frontend/
│   ├── app/{layout,page}.tsx, globals.css   # 1065 dòng CSS, token-driven, theme Wealify
│   ├── components/
│   │   ├── ChatPane.tsx, Message.tsx, Badges.tsx, DraftModal.tsx, BrandMark.tsx
│   │   ├── Sidebar.tsx                       # gợi ý câu hỏi + info tài khoản + toggle
│   │   └── evidence/                         # drawer "Bằng chứng & dữ liệu"
│   │       ├── Evidence.tsx                  # 5 nhóm tab / 10 view
│   │       ├── AlertsView / MoneyViews / ReconViews / SystemViews / BoundariesView
│   ├── lib/{api,types,i18n,markdown}.ts
│   └── public/fonts/         # Manrope self-hosted (3 subset, có subset vietnamese cho ₫)
│
├── scripts/  setup.sh · run.sh · deploy.sh · smoke.sh · purge.sh
└── docs/     De-bai.md · WLF-01_Ke_hoach_lam_viec.md · DESIGN.md · Giai-ngo-nghiep-vu.md
```

---

## 4. Luồng dữ liệu

```
dataset/*.csv
     │  loader.py chọn shape → loader_wlf.py parse export Wealify
     ▼
  Dataset  { account[], card[], wallet, emails[], cards[], virtual_accounts[], meta, notes }
     │
     ▼  pipeline.run()   ← ĐIỂM VÀO DUY NHẤT, cache 1 lần / process (lru_cache)
     ├── classify.classify()        → dòng tiền: payin/payout/transfer/fee/purchase
     ├── email_match.reconcile()    → mỗi giao dịch: matched | no_email_found | email_suspicious
     ├── subscriptions.detect()     → gói định kỳ, cadence, next charge, tăng giá, quên huỷ
     ├── tri_source.reconcile()     → account ↔ wallet ↔ card: chưa lên thẻ / nạp trùng / lệch ví
     └── anomaly.detect()           → trùng, phí kép, merchant lạ, thiếu biên lai
     ▼
  Finding[]   (kind, label, confidence, params, sources[], txn_ids[], amount, deadline)
     │  labels.py gắn 1 trong 3 nhãn · render.py dịch VI/EN từ cùng params
     ▼
  ┌────────────────────────┬──────────────────────────────┐
  │ routers/* → serialize  │ llm/tools.py (14 tool đọc)    │
  │ → JSON cho UI          │ → chat.py → guardrail → reply │
  └────────────────────────┴──────────────────────────────┘
                                    │
                          monitor.run_scan() → store (Postgres)
                          fingerprint → chống báo trùng
```

### Vòng đời 1 câu chat ([llm/chat.py](../backend/app/llm/chat.py))

```
question
  1. guardrails.classify_intent()   → HARD blocked? → từ chối + đưa cái LÀM ĐƯỢC (hướng dẫn
                                       tự huỷ / bằng chứng để tự khiếu nại). Không tool nào chạy.
                                     → SOFT (câu "có an toàn không") → từ chối kết luận,
                                       nhưng VẪN show findings
  2. client.route()                 → keyword table trước (miễn phí, chính xác cho dataset này),
                                       model sau nếu keyword không kết luận được
                                     → chat_only = câu chào/cảm ơn, không cần dữ liệu
  3. run_tool(name, args)           → CHỈ arg đã khai báo trong ALLOWED_ARGS được truyền
  4. client.narrate()               → model kể lại tool result thành câu
  5. guardrails.check_output()      → chặn câu trấn an + ám chỉ ngân hàng đang điều tra
     _numbers_grounded()            → mọi $, ₫, ACC-/CRD- trong câu trả lời PHẢI có trong
                                       tool result; không có → retry 1 lần → fallback
                                       summarize.summarize() (câu của engine)
  6. scrub_text()                   → net cuối: mọi dãy 12–19 chữ số bị mask
```

Field `source` trong response cho biết câu trả lời đến từ đâu: `llm` · `llm_retry` ·
`deterministic_fallback` · `llm_unavailable` · `llm_error` · `smalltalk_canned` · `guardrail`.
UI hiển thị chip provenance này.

---

## 5. Module backend — file nào làm gì

### `app/engine/` — logic phát hiện (pure Python, không import web/LLM)

| File | Dòng | Việc |
|---|---|---|
| [models.py](../backend/app/engine/models.py) | 514 | Dataclass + enum gốc. Tiền = **integer cents** (tổng luôn chính xác). `TxnType`, `CardTxnType`, `TxnStatus`, `Label` (chỉ 3 giá trị), `FindingKind` (11 loại), `Finding.fingerprint`, `dispute_deadline` = statement_date + 60 ngày. `fmt_display()` → VI dẫn ₫ + kèm USD chính xác |
| [loader.py](../backend/app/engine/loader.py) | 302 | `Dataset`, `load_dataset()` chọn shape input, parse CSV/PDF/JSON/.eml của bộ mẫu |
| [loader_wlf.py](../backend/app/engine/loader_wlf.py) | 919 | Parse export Wealify thật. **File phức tạp nhất** — xem mục 8 |
| [merchants.py](../backend/app/engine/merchants.py) | 255 | Descriptor → merchant. Từ điển curated + prefix xử lý (`SQ *`, `PP*`, `PADDLE.NET*`). Không khớp → trả `None`, KHÔNG đoán tên |
| [classify.py](../backend/app/engine/classify.py) | 235 | Phân loại dòng tiền. `settled()` loại dòng declined/cancelled khỏi mọi tổng nhưng vẫn liệt kê riêng. Tổng tách theo currency |
| [email_match.py](../backend/app/engine/email_match.py) | 308 | Ghép giao dịch ↔ email (window ±3 ngày, threshold 0.70). Detect email giả: display name khai brand mà domain lệch, domain edit-distance ≤2, reply-to khác domain. Câu ép buộc chỉ là **tín hiệu phụ** |
| [subscriptions.py](../backend/app/engine/subscriptions.py) | 335 | ≥3 lần charge, gap trung vị theo cadence (weekly 6–8 / monthly 26–35 / quarterly 85–95 / yearly 350–380), SD ≤ ngưỡng. Gom theo **merchant**, không theo số tiền → đổi giá không tách chuỗi. Next charge = cùng ngày-trong-tháng, clamp độ dài tháng. Quên huỷ = 3 kỳ cuối không có biên lai |
| [anomaly.py](../backend/app/engine/anomaly.py) | 295 | Trùng: cùng merchant + cùng số tiền + ≤15 phút. Phí kép: cùng descriptor + cùng ngày + count>1. Thiếu biên lai: purchase ≥ **percentile 90 của chính người dùng** (thích ứng theo người, không phải số cứng) |
| [tri_source.py](../backend/app/engine/tri_source.py) | 451 | Mỗi `transfer_to_card` phải có card load khớp ref, hoặc khớp amount trong ±3 ngày. Nạp trùng: window 24h (không bucket theo ngày — export stamp UTC, cặp cách 3h có thể nằm 2 bên nửa đêm). Lệch ví: `opening + Σ events` vs balance báo cáo → **nêu số lệch, không đoán nguyên nhân** |
| [reports.py](../backend/app/engine/reports.py) | 236 | Báo cáo tháng/quý/năm + so kỳ trước + series 12 tháng |
| [labels.py](../backend/app/engine/labels.py) | 78 | Map `FindingKind → Label`. **Chỉ 3 nhãn tồn tại**, không có giá trị "fraud/not fraud" ở đâu cả |
| [dedupe.py](../backend/app/engine/dedupe.py) | 92 | `Finding` → flag lưu được; `journal_reason()` sinh 1 dòng lý do cho audit log; export CSV/JSON |
| [mask.py](../backend/app/engine/mask.py) | 52 | `mask_card` → `•••• 4821`, `mask_account` → `••••••6390`, `scrub_text` net cuối |
| [render.py](../backend/app/engine/render.py) | 177 | Findings → câu VI/EN từ catalog i18n. Cả 2 ngôn ngữ đọc **cùng params** → không thể lệch số |
| [pipeline.py](../backend/app/engine/pipeline.py) | 174 | `run()`, `cached()`, `Analysis` (summary, alerts, account_profile) |

### `app/llm/`

| File | Dòng | Việc |
|---|---|---|
| [tools.py](../backend/app/llm/tools.py) | 581 | **Toàn bộ khả năng của model** = 14 tool đọc + `SPECS` (JSON-schema) + `ALLOWED_ARGS` (whitelist arg) + `run_tool()` |
| [client.py](../backend/app/llm/client.py) | 613 | **2 transport chọn theo `.env`**: `OllamaBackend` (`/api/tags`, `/api/chat`, `/api/show`) và `OpenAIBackend` (`/models`, `/chat/completions`, có Bearer key) — response được normalise về cùng shape `{"message": ...}` nên phần còn lại provider-agnostic. Kèm `KEYWORD_ROUTES` (route deterministic) + `extract_args()` (bóc amount/ref/period/merchant khỏi câu hỏi) |
| [guardrails.py](../backend/app/llm/guardrails.py) | 209 | 6 blocked intent (VI+EN regex) · `BANNED_OUTPUT` (câu trấn an) · `BANNED_IMPLICATION` (ám chỉ bank đang giữ/điều tra) · `_approved_phrases()` blank câu từ chối của chính mình trước khi match (nếu không filter sẽ tự bắn vào chính nó) |
| [prompts.py](../backend/app/llm/prompts.py) | 196 | System prompt + `humanize()` (rút gọn tool result trước khi đưa model) |
| [summarize.py](../backend/app/llm/summarize.py) | 297 | Câu trả lời **deterministic** cho từng tool — dùng khi model die hoặc bị reject |
| [smalltalk.py](../backend/app/llm/smalltalk.py) | 57 | Nhận diện chào/cảm ơn/"bạn là ai" |
| [chat.py](../backend/app/llm/chat.py) | 242 | Orchestration (xem mục 4) |

**14 tool:** `get_overview` · `get_cashflow` · `list_subscriptions` · `get_findings` ·
`get_email_recon` · `get_tri_source` · `get_report` · `explain_charge` ·
`search_transactions` · `get_reminders` · `run_monitor_scan` · `draft_report_email` ·
`get_cancellation_guide` · `get_audit_log`.

Tool duy nhất có thể gây tác động ra ngoài là `draft_report_email` — nó **chỉ tạo nháp**
và trả confirm token; gửi là endpoint riêng, cần người dùng xác nhận.

### Provider — quyết định hoàn toàn bởi `.env`

| `NEXA_AI_PROVIDER` | Nói chuyện với | Cần gì |
|---|---|---|
| `ollama` | Ollama chạy local | `NEXA_AI_URL=http://localhost:11434` |
| `openai` | Mọi endpoint OpenAI-compatible: BytePlus Ark, OpenAI, Groq, Together, vLLM, llama.cpp server | `NEXA_AI_URL=https://…/v1` hoặc `/api/v3` + `NEXA_AI_API_KEY` |
| `auto` *(mặc định)* | Sniff theo URL (`/v1`, `/api/v3`, tên nhà cung cấp) + có key hay không, rồi probe cái còn lại | — |

Key chỉ đọc từ environment; không log, không trả qua API, không đẩy ra browser.

### 3 tier LLM (tự chọn lúc startup, hiển thị dưới mỗi câu trả lời)

1. **native_tools** — model khai báo (Ollama probe `/api/show`) hoặc **chấp nhận**
   tool calling (endpoint OpenAI-compatible: mặc định giả định có, bị reject schema
   thì **tự hạ tier** xuống json_router cho cả process — `ToolsUnsupported`)
2. **json_router** — model chat thường, trả `{"tool": ..., "args": ...}`
3. **offline** — không với tới model / `NEXA_OFFLINE_MODE=true` → engine tự trả lời,
   vẫn đủ 2 ngôn ngữ. `detail` trong `/api/health` nói **lý do cụ thể**: sai key
   (401/403), sai base path (404), model không có trong listing

---

## 6. API endpoint

| Method | Path | Việc |
|---|---|---|
| GET | `/` | ping + link |
| GET | `/api/health` | dataset counts, DB, LLM status, mail mode, owner_email, tỷ giá |
| GET | `/api/i18n/{lang}` · `/api/disclaimer` | catalog câu chữ · dòng nhắc bắt buộc |
| GET | `/api/summary` | tổng quan: account profile, counts, label tally, cashflow, findings |
| GET | `/api/cashflow` | phân loại dòng tiền |
| GET | `/api/subscriptions` | gói định kỳ + next charge + tăng giá |
| GET | `/api/findings` | `?kind=&label=&alerts_only=` |
| GET | `/api/email-recon` | bảng giao dịch ↔ email, `?ref=&status=` |
| GET | `/api/tri-source` | đối chiếu 3 nguồn |
| GET | `/api/statement` | sao kê thật, `?source=account\|card`, đã mask |
| GET | `/api/search` | filter text / min_amount / date range / flow_type |
| GET | `/api/explain` | giải thích 1 khoản, `?ref=\|amount=\|descriptor=` |
| GET | `/api/report` · `/api/report/all` | 1 kỳ · month+quarter+year + trend 12 tháng |
| POST | `/api/chat` | `{question, lang}` → câu trả lời + tool + data + provenance |
| POST | `/api/report/draft` | tạo nháp + confirm token (**không gửi**) |
| POST | `/api/report/send` | cần `confirmed=true` (nếu không → **428**) + token; recipient ≠ owner → **403**; token dùng 1 lần, sai/đã dùng → **409** |
| POST | `/api/monitor/scan` | quét lại, trả **chỉ cái mới** + số bị suppress |
| GET | `/api/monitor/reminders` · `/history` | nhắc hạn 60 ngày · lịch sử scan |
| GET | `/api/audit` · `/audit/export` · `/audit/flags` | nhật ký · export CSV/JSON · flag đã lưu |
| POST | `/api/audit/purge` | xoá sạch state (quy định 9 của đề) |

Frontend gọi **same-origin**: `next.config.mjs` rewrite `/api/*` → `BACKEND_URL` ⇒ không cần
cấu hình CORS trên máy giám khảo.

---

## 7. 3 nhãn, mốc 60 ngày, chống báo trùng

### 3 nhãn — không có nhãn thứ 4 trong code

| Nhãn | Nghĩa | Loại finding |
|---|---|---|
| `recurring_confirmed` — *Định kỳ đã xác định* | Chứng minh được từ sao kê | recurring_subscription, price_increase |
| `needs_your_confirmation` — *Cần bạn tự xác nhận* | Phụ thuộc ý định người dùng | forgotten_subscription, duplicate_charge, double_fee, duplicate_payin, transfer_not_on_card, missing_email |
| `insufficient_data` — *Chưa đủ dữ liệu* | Dữ liệu không kết luận được | wallet_balance_mismatch, unknown_merchant, suspicious_email |

### Mốc khiếu nại

`dispute_deadline = statement_date + 60 ngày`. Hiện trên mọi finding + sinh reminder cho
2 nhãn cần review. Quá hạn → badge màu rose (là **sự thật**, không phải phán xét).

### Chống báo trùng

`fingerprint = sha256(kind | sorted(txn_ids) | amount_cents | period_key)[:32]`, là
PRIMARY KEY bảng `flags`. `run_scan()` chỉ báo fingerprint chưa có, ghi số bị suppress vào
journal. Scan thủ công và cron 07:00 dùng **cùng một hàm** → hành vi giống nhau.

### Postgres — 5 bảng ([store.py](../backend/app/store.py))

`scans` · `flags` · `audit_log` · `reminders` · `report_drafts`. **Không bảng nào chứa tiền
của người dùng** — chỉ state ứng dụng. Postgres chết thì phân tích vẫn chạy; chỉ journal /
dedupe / reminder là mất.

---

## 8. Những chỗ dữ liệu "bẫy" trong export Wealify

[loader_wlf.py](../backend/app/engine/loader_wlf.py) tồn tại vì 5 lý do sau — đọc trước khi sửa loader:

1. **1 file, 2 sổ.** `transactions_card.csv` có cột `source_type`: `Thẻ` = dòng chạm số dư
   thẻ, `Ví` = chạm ví. Cột `type` viết tiếng Việt theo góc nhìn nền tảng — `Rút tiền về ví`
   là tiền **rời ví** sang thẻ. ⇒ type luôn đọc kèm reference + dấu, không tin nhãn.
2. **Không có sổ tài khoản nhận.** `virtual_accounts.csv` chỉ có `total_received` tổng.
   `transactions_va.csv` — dù tên vậy — **không chứa dòng VA nào**, là bản copy cũ của
   card/wallet với text tiếng Việt bị hỏng encoding ⇒ **detect theo nội dung rồi skip**
   (parse vào sẽ nhân đôi mọi con số thẻ). Vì vậy `VirtualAccount.has_ledger = False`,
   và mọi kiểm tra cần dòng đó phải trả `insufficient_data`.
3. **Placeholder nằm trong cột số.** `fee` = `NaN undefined` trên 192/193 dòng,
   `exchange_rate` = `NaN = 1 USD`. ⇒ parse thành `None`, **không bao giờ thành `0`**, cũng
   không thành `float('nan')` (sẽ đầu độc mọi tổng).
4. **3 format ngày, 2 quy ước thập phân.** Transaction `21/08/2026 | 01:27 PM`; bảng thẻ
   `14/8/26 14:00` **và dùng dấu phẩy thập phân** (`49,7` = 49.70); bảng account ISO-8601 `Z`
   với dấu phẩy hàng nghìn (`1,936.92 USD`).
5. **Hộp thư là relay.** Mọi mail do sandbox `no-reply@wealify.com` gửi; người gửi mà **người
   dùng được yêu cầu tin** nằm trong body sau `Người gửi gốc (CSV)`. ⇒ detect email giả phải
   đọc field đó, không đọc envelope.

Ngoài ra: dòng chưa settle (declined/cancelled/pending) **không bao giờ bị cộng vào tổng và
cũng không bị âm thầm bỏ đi** — báo riêng ở `unsettled`. Tổng tách theo currency (account
này giữ nhiều loại tiền, cộng chung sẽ ra số vô nghĩa).

---

## 9. Guardrails (được bảo đảm bằng code, không bằng prompt)

| Rule | Bảo đảm ở đâu |
|---|---|
| Không tác động tới tiền | Không có hàm cancel/dispute/transfer/freeze ở bất kỳ đâu. Model chỉ thấy 14 tool đọc |
| Email chỉ gửi cho chính chủ | `mailer.assert_owner()`; owner đọc từ `account_meta.json` hoặc `cards.csv`; **không đọc được → trả "" → refuse hẳn** (fail closed) |
| Phải xác nhận trước khi gửi | Token dùng 1 lần + `confirmed=true`; thiếu → 428, sai recipient → 403 (**check trước cả token**), token xấu → 409 |
| Thư cho bên thứ ba | Chỉ sinh nháp — không tồn tại đường gửi |
| Không bịa số | Grounding check mọi `$`, `₫`, `ACC-/CRD-` → retry 1 lần → thay bằng câu của engine |
| Không trấn an | `BANNED_OUTPUT` VI+EN; câu từ chối của chính mình được exempt |
| Không ám chỉ bank đang xử lý | `BANNED_IMPLICATION` |
| Mask | Mask tại boundary (API, log, prompt LLM). **Không model nào có field CVV** ⇒ không thể lưu |
| Không báo trùng | Fingerprint + unique constraint |
| Audit được | Mỗi lần gắn cờ ghi khoản/lý do/confidence/nguồn → export CSV/JSON |

UI có tab **"Ranh giới an toàn"** ([BoundariesView.tsx](../frontend/components/evidence/BoundariesView.tsx))
liệt kê 6 việc Nexa không làm + **lý do ở tầng code**, kèm nút "Thử" để giám khảo tự kiểm chứng.

3 câu gài của đề được **trộn lẫn** vào danh sách gợi ý trong sidebar, không gắn nhãn riêng —
"một sản phẩm không quảng cáo cái nó sẽ từ chối".

---

## 10. Test — 177 test

| File | Kiểm |
|---|---|
| [test_ground_truth.py](../backend/tests/test_ground_truth.py) | So engine với `ground_truth.json`: 15 finding phải có đủ, **4 near-miss phải KHÔNG bị flag** (over-flag = fail), nhãn, nguồn, deadline, tổng báo cáo, dự báo, parity CSV↔PDF |
| [test_export_dataset.py](../backend/tests/test_export_dataset.py) | 25 test cho 5 cái bẫy ở mục 8: placeholder không thành số, 2 quy ước thập phân, mọi format ngày, status lạ fail-closed, file cũ detect theo nội dung, không lưu PAN/phone, tách 2 sổ, sender đọc từ body |
| [test_guardrails.py](../backend/tests/test_guardrails.py) | 3 câu gài bị classify đúng, câu hợp lệ **không** bị block, request hành động không chạy tool nào, mọi câu trả lời có dòng nhắc bắt buộc |
| [test_dedupe.py](../backend/tests/test_dedupe.py) | Scan lần 2 không báo gì mới, fingerprint ổn định qua reload, reminder tạo 1 lần |
| [test_mail.py](../backend/tests/test_mail.py) | Owner-only, draft không gửi, token dùng 1 lần, bên thứ ba bị refuse **trước** khi check token |
| [test_masking.py](../backend/tests/test_masking.py) | Endpoint không leak, **không field CVV nào tồn tại trong models**, dataset không chứa CVV |
| [test_smalltalk.py](../backend/tests/test_smalltalk.py) | Chào hỏi không cần tool, câu hỏi thật không bị coi là smalltalk |
| [test_llm.py](../backend/tests/test_llm.py) | Opt-in (`NEXA_TEST_LLM=1`): model reachable, output grounded, prompt injection không mở được hành động |
| [test_ai_provider.py](../backend/tests/test_ai_provider.py) | Chọn transport theo URL/key, provider set tay không bị override, reshape reply OpenAI → shape router đọc, endpoint đổi tên `max_tokens` được retry, reject tool schema → hạ tier chứ không giả smalltalk, 401 → báo đúng "thiếu key", **API key không bao giờ xuất hiện trong status** |

`make test` (86 test) · `make test-llm` (test cần model) · `make smoke` (curl stack đang chạy)

---

## 11. Lệnh hay dùng

```bash
make setup      # venv + pip + npm + postgres + sinh dataset mẫu
make dev        # backend :8000 (reload) + frontend :3000
make test       # 86 test
make smoke      # curl stack đang chạy, check rule an toàn
make seed       # sinh lại dataset mẫu + đáp án chuẩn
make deploy     # build & run toàn bộ trong Docker, rồi chạy smoke
make purge      # xoá dataset mẫu, outbox, log, toàn bộ state DB (quy định 9)
make stop       # kill uvicorn + next + docker compose down
```

Config qua `.env` (prefix `NEXA_`). Đáng chú ý:

- **Model**: `NEXA_AI_PROVIDER` (`auto`/`ollama`/`openai`) · `NEXA_AI_URL` ·
  `NEXA_AI_API_KEY` · `NEXA_AI_MODEL` · `NEXA_AI_NATIVE_TOOLS` (`auto`/`true`/`false`) ·
  `NEXA_OFFLINE_MODE` · `NEXA_AI_RETRIES`
- **Dữ liệu**: `NEXA_DATA_DIR` (mặc định `./dataset` = export Wealify; trỏ
  `backend/data/sample` để dùng bộ có đáp án chuẩn) · `NEXA_MAILBOX`
  (`tester`/`senior`/`junior`, rỗng = chọn theo inbox đăng ký với cards.csv)
- **Khác**: `NEXA_USD_VND_RATE` (26.000, hiện ở footer UI + `/api/health`) ·
  `NEXA_MAIL_MODE` · `NEXA_SCAN_HOUR`

Kiểm tra model có sống không:

```bash
curl -s localhost:8000/api/health | python3 -m json.tool | grep -A 6 '"llm"'
```

---

## 12. Quy ước cần giữ khi sửa code

- **Tiền = integer cents** trong toàn engine. Chỉ đổi sang dollar ở `serialize.to_dollars()`.
  Field `x_cents` tự động thành `x_usd` + chuỗi hiển thị ở boundary.
- **VI/EN đọc cùng `params`** qua `render.t()` — không hardcode câu tiếng Việt trong engine.
- **Không thêm nhãn thứ 4.** `Label` chỉ có 3 giá trị; thêm là phá rule C của đề.
- **Không đoán tên merchant.** Không khớp từ điển → `None` → báo "chưa xác định được".
- **Không đoán nguyên nhân lệch.** Nêu số lệch rồi dừng.
- **Thêm tool mới phải là read-only**, và phải khai `ALLOWED_ARGS` (arg không khai sẽ bị drop).
- **`engine/` không được import web/LLM** — đó là lý do mọi con số bị chấm điểm đều test được.
- **Dữ liệu thiếu → `None`, không phải `0`.** Một số 0 bịa ra sẽ trở thành "gap = 0" giả.

---

## 13. Điểm cần lưu ý / hạn chế đã biết

- **`.env` cần `NEXA_AI_API_KEY`.** File `.env` local trỏ tới BytePlus Ark
  (`https://ark.ap-southeast.bytepluses.com/api/v3`, model `deepseek-v4-flash-260425`).
  Transport OpenAI-compatible đã có, nhưng chưa có key ⇒ probe trả **HTTP 401** ⇒ status
  `offline` ⇒ trả lời bằng engine. Điền key vào `NEXA_AI_API_KEY` là chạy.
- Chạy trong Docker với Ollama **local**: container không với tới Ollama bind localhost ⇒ cần
  `OLLAMA_HOST=0.0.0.0 ollama serve`. Endpoint hosted thì không cần gì thêm. Không có cả hai
  thì stack vẫn trả lời — bằng engine.
- **13 test trong `backend/tests/test_wlf_export.py` đang fail** (file untracked, không nằm
  trong 86 test của `make test`): guardrail cancel không khớp dạng số nhiều
  (`subscriptions`/`plans`/`memberships`), tách 5 bucket dòng tiền, và nhãn category. Không
  liên quan tầng LLM.
- Từ điển merchant là danh sách curated; ngoài danh sách → báo "chưa xác định được" (**cố ý**).
- Tỷ giá ₫ là rate mình cấu hình, luôn ghi "≈", không phải rate ngân hàng.
- Model nhỏ đôi khi diễn đạt lỏng ⇒ grounding check thay bằng câu của engine, và câu trả lời
  được đánh dấu *máy phân tích trả lời trực tiếp*.
- Bộ đáp án chuẩn (`ground_truth.json`) chỉ có cho **dataset sinh ra** (`backend/data/sample`),
  không có cho export Wealify thật trong `dataset/` — test answer-key vì vậy pin cứng thư mục
  sample thay vì đi theo `settings.data_dir`.
