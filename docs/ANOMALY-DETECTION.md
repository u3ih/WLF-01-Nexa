# Thuật Toán Phát Hiện Giao Dịch Bất Thường — Anomaly Detection

## Tổng Quan

Hệ thống phát hiện giao dịch bất thường (anomaly detection) của Nexa được xây dựng
dựa trên **14 detection rules** (luật phát hiện), bao trùm hầu hết các nguyên lý
đối soát và kiểm soát doanh thu đã được tài liệu hoá:

| # | Rule | File | Finding Kind |
|---|---|---|---|
| 1 | **Exact duplicate** — trùng chính xác | `duplicate_charges()` | `duplicate_charge` |
| 2 | **Suspected duplicate** — nghi trùng mờ | `suspected_duplicates()` | `suspected_duplicate` |
| 3 | **Off-hours transaction** — ngoài giờ | `off_hours_transactions()` | `off_hours_txn` |
| 4 | **Rapid spending** — chi tiêu dồn dập | `rapid_spending()` | `rapid_spending` |
| 5 | **Spending spike** — tăng đột biến | `spending_spike()` | `spending_spike` |
| 6 | **Category concentration** — tập trung DM | `category_concentration()` | `category_concentration` |
| 7 | **Late refund** — hoàn tiền muộn | `late_refunds()` | `late_refund` |
| 8 | **Sub no welcome** — đăng ký không email | `_subscription_first_charge_no_welcome()` | `sub_no_welcome` |
| 9 | **Charged after cancel** — trừ sau khi hủy | `_charged_after_cancel()` | `charged_after_cancel` |
| 10 | **Free trial converted** — hết dùng thử | `_free_trial_converted()` | `free_trial_converted` |
| 11 | **Double fees** — phí kép | `double_fees()` | `double_fee` |
| 12 | **Unknown merchant** — merchant lạ | `unknown_merchants()` | `unknown_merchant` |
| 13 | **Missing receipt** — thiếu biên lai | `missing_receipts()` | `missing_email` |
| 14 | **Suspicious email** — email giả mạo | `suspicious_email_findings()` | `suspicious_email` |

Hệ thống được thiết kế theo các nguyên lý cốt lõi từ tài liệu nguyên lý đối soát:

- **Multi-source reconciliation** — đối chiếu nhiều nguồn (account, card, wallet, email)
- **Drill-down capability** — mọi cảnh báo đều có sources dẫn đến từng giao dịch
- **Fingerprint-based deduplication** — chống trùng cảnh báo qua các lần quét
- **Confidence scoring** — mức độ chắc chắn của từng phát hiện
- **Alert lifecycle** — trạng thái cảnh báo (NEW → CONFIRMED → RESOLVED)
- **Label system** — 3 mức: recurring_confirmed / needs_your_confirmation / insufficient_data

---

## Kiến Trúc & Luồng Dữ Liệu

```
┌─────────────────────────────────────────────────────────────┐
│                     DATASET (Loader)                        │
│  account_statement.csv │ card_statement.csv │ wallet.json  │
└─────────────────────────┴────────────────────┴─────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   ENGINE PIPELINE (pipeline.py)              │
│                                                             │
│  Classify → Email Match → Subscriptions → Tri-source → Anomaly  │
│                                                             │
│                     Findings (List)                         │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   API ENDPOINTS (FastAPI)                    │
│  GET /api/summary  │  GET /api/findings  │  GET /api/audit  │
└─────────────────────────────────────────────────────────────┘
```

---

## Chi Tiết 14 Detection Rules

### 1. Exact Duplicate Charges — Trùng Chính Xác

**File**: `anomaly.py` → `duplicate_charges()`  **Nguyên lý**: §5 — Kiểm soát giao dịch trùng  **Window**: 15 phút  **Điều kiện**: Cùng `merchant_key` + cùng `amount_cents`  **Confidence**: 0.75

Phát hiện hai giao dịch giống hệt nhau về merchant và số tiền, xảy ra trong vòng
15 phút. Dùng `merchant_key` (đã được chuẩn hoá từ descriptor) làm khóa so sánh.

```python
groups[(charge.merchant_key, abs(charge.amount_cents))].append(charge)
for first, second in zip(charges, charges[1:]):
    gap = (second.when - first.when).total_seconds()
    if gap > DUPLICATE_WINDOW_SECONDS:  # 900s
        continue
    # ra finding DUPLICATE_CHARGE
```

---

### 2. Suspected Duplicate — Nghi Trùng Mờ (Fuzzy)

**File**: `anomaly.py` → `suspected_duplicates()`  **Nguyên lý**: §5 — Kết hợp nhiều thuộc tính  **Window**: 24 giờ  **Similarity tối thiểu**: 80% (Levenshtein ratio)  **Dung sai số tiền**: ±15%  **Confidence**: 0.40 ~ 0.70

Khi không có correlation key duy nhất, kết hợp nhiều thuộc tính: thời gian gần
nhau (24h), số tiền tương tự (±15%), mô tả merchant tương đồng (Levenshtein ≥80%).

```python
similarity = _levenshtein_ratio(norm_a, norm_b)
ratio = min(amt_a, amt_b) / max(amt_a, amt_b)
if similarity >= 0.80 and ratio >= 0.85:
    # ra finding SUSPECTED_DUPLICATE
```

---

### 3. Off-Hours Transaction — Giao Dịch Ngoài Giờ

**File**: `anomaly.py` → `off_hours_transactions()`  **Nguyên lý**: §8 — Rule-based detection  **Khung giờ**: 23:00 – 06:00  **Confidence**: 0.40

Flag các giao dịch phát sinh ngoài khung giờ sinh hoạt bình thường. Có thể là
dấu hiệu của giao dịch tự động (subscription), gian lận thẻ, hoặc mua sắm bất
thường.

---

### 4. Rapid Spending — Chi Tiêu Dồn Dập

**File**: `anomaly.py` → `rapid_spending()`  **Nguyên lý**: §8 — Rule-based detection  **Ngưỡng**: ≥ 3 giao dịch trong 30 phút  **Confidence**: 0.55

Phát hiện các cụm giao dịch với tần suất cao bất thường. Sử dụng sliding window
để tránh đếm trùng.

---

### 5. Spending Spike — Tăng Chi Tiêu Đột Biến

**File**: `anomaly.py` → `spending_spike()`  **Nguyên lý**: §9 — Trend / outlier analysis  **Điều kiện**: `spend > previous × 1.5` HOẶC `spend > mean + 2σ`  **Confidence**: 0.50 / 0.65

So sánh chi tiêu tháng hiện tại với tháng trước (relative) và rolling mean
(absolute), đồng thời xác định top 3 merchant đóng góp nhiều nhất.

---

### 6. Category Concentration — Tập Trung Danh Mục

**File**: `anomaly.py` → `category_concentration()`  **Nguyên lý**: §9 — Phân tích nhóm  **Ngưỡng**: Một danh mục ≥ 60% tổng chi tiêu  **Confidence**: 0.50

Tính tỷ trọng từng danh mục merchant so với tổng chi tiêu. Nếu một danh mục
chiếm ≥ 60%, đánh dấu là bất thường.

---

### 7. Late Refund — Hoàn Tiền Muộn

**File**: `anomaly.py` → `late_refunds()`  **Nguyên lý**: §8 — Rule-based detection  **Ngưỡng**: Hoàn tiền sau ≥ 30 ngày  **Confidence**: 0.50

Tìm các giao dịch hoàn tiền đến sau 30 ngày kể từ giao dịch gốc. Dùng best-match
dựa trên số tiền (≥80% giá trị gốc) và khoảng cách thời gian.

---

### 8. Subscription No Welcome Email

**File**: `anomaly.py` → `_subscription_first_charge_no_welcome()`  **Nguyên lý**: §7 — Lifecycle / state transition  **Điều kiện**: Giao dịch đầu tiên ≥ 2 giao dịch, không có email khớp  **Confidence**: 0.40

Nếu một gói định kỳ có từ 2+ giao dịch nhưng giao dịch đầu tiên không tìm thấy
email chào mừng, đây có thể là dấu hiệu đăng ký trái phép.

---

### 9. Charged After Cancel

**File**: `anomaly.py` → `_charged_after_cancel()`  **Nguyên lý**: §7 — Lifecycle / state transition  **Ngưỡng**: Khoảng cách ≥ 45 ngày giữa 2 lần trừ  **Confidence**: 0.50

Phát hiện giao dịch sau khoảng trống bất thường (>45 ngày), gợi ý người dùng
đã hủy nhưng vẫn bị trừ tiền.

---

### 10. Free Trial Converted

**File**: `anomaly.py` → `_free_trial_converted()`  **Nguyên lý**: §7 — Lifecycle / state transition  **Điều kiện**: Giá tăng ≥ 1.5× trong vòng ≤ 45 ngày  **Confidence**: 0.55

Giao dịch đầu tiên nhỏ (dùng thử), giao dịch thứ hai lớn hơn rõ rệt (≥1.5×)
trong vòng 45 ngày — tín hiệu chuyển từ dùng thử sang trả phí.

---

### 11–14. Legacy Detectors

| # | Function | Finding Kind | Mô tả |
|---|---|---|---|
| 11 | `double_fees()` | `double_fee` | Cùng loại phí, cùng ngày, ≥2 lần |
| 12 | `unknown_merchants()` | `unknown_merchant` | Descriptor không resolve được |
| 13 | `missing_receipts()` | `missing_email` | Giao dịch lớn > p90 không có email |
| 14 | `suspicious_email_findings()` | `suspicious_email` | Email có dấu hiệu giả mạo |

---

## Confidence Score & Label System

### Confidence Score (0.0 – 1.0)

| Score | Ý nghĩa | Áp dụng cho |
|---|---|---|
| 0.85 | Rất chắc chắn | Double fee, duplicate charge |
| 0.70-0.75 | Khá chắc chắn | Missing receipt, exact duplicate |
| 0.50-0.65 | Trung bình | Spending spike, rapid spend, late refund |
| 0.40 | Thấp | Off-hours, suspected duplicate |

### Label System (3 mức)

| Label | Ý nghĩa | Hành động |
|---|---|---|
| `needs_your_confirmation` | Cần người dùng tự xác nhận | User phải kiểm tra thủ công |
| `insufficient_data` | Chưa đủ dữ liệu để kết luận | Cần thêm thông tin |
| `recurring_confirmed` | Định kỳ đã xác nhận | Chỉ mang tính thông tin |

---

## Fingerprint & Chống Trùng Lặp

**File**: `dedupe.py`

Mỗi finding có một `fingerprint` (SHA256 hash) duy nhất, giúp tránh gửi cảnh báo
trùng qua các lần quét và cho phép cập nhật trạng thái thay vì tạo bản ghi mới.

```python
@property
def fingerprint(self) -> str:
    basis = "|".join([
        self.kind.value,
        ",".join(sorted(self.txn_ids)),
        str(self.amount_cents),
        self.period_key,
    ])
    return hashlib.sha256(basis.encode()).hexdigest()[:32]
```

Cơ chế: `run_scan()` → `detect()` → `split_new(findings, known)` → (new, suppressed)

---

## API Endpoints

| Endpoint | Mô tả |
|---|---|
| `GET /api/summary` | Tổng quan toàn bộ phân tích, gồm findings |
| `GET /api/findings` | Danh sách findings (filter: kind, label, alerts_only) |
| `GET /api/audit/flags` | Các flag đã lưu trong database |

### GET /api/findings — Parameters

| Param | Type | Mô tả |
|---|---|---|
| `lang` | string | "vi" hoặc "en" |
| `kind` | string | Lọc theo loại (VD: "duplicate_charge") |
| `label` | string | Lọc theo label (VD: "needs_your_confirmation") |
| `alerts_only` | bool | Mặc định true, chỉ lấy cảnh báo |

---

## Cấu Hình (Configuration)

Các hằng số trong `anomaly.py`:

| Hằng số | Mặc định | Ý nghĩa |
|---|---|---|
| `DUPLICATE_WINDOW_SECONDS` | 900 (15p) | Cửa sổ trùng chính xác |
| `SUSPECTED_DUP_SIMILARITY` | 0.80 | Ngưỡng similarity Levenshtein |
| `SUSPECTED_DUP_AMOUNT_TOLERANCE` | 0.15 (±15%) | Dung sai số tiền |
| `SUSPECTED_DUP_WINDOW_SECONDS` | 86400 (24h) | Cửa sổ nghi trùng |
| `OFF_HOURS_START` | 23 (11pm) | Giờ bắt đầu ngoài giờ |
| `OFF_HOURS_END` | 6 (6am) | Giờ kết thúc ngoài giờ |
| `RAPID_SPEND_COUNT` | 3 | Số giao dịch tối thiểu |
| `RAPID_SPEND_WINDOW_MINUTES` | 30 | Cửa sổ chi tiêu dồn dập |
| `CATEGORY_CONCENTRATION_THRESHOLD` | 0.60 (60%) | Ngưỡng tập trung DM |
| `SPENDING_SPIKE_MULTIPLIER` | 1.50 | Ngưỡng tăng so với tháng trước |
| `SPENDING_SPIKE_STDDEV` | 2.0 (2σ) | Số sigma trên mean |
| `LATE_REFUND_DAYS` | 30 | Ngưỡng hoàn tiền muộn |
| `FREE_TRIAL_MAX_DAYS` | 45 | Thời gian dùng thử tối đa |

---

## Cách Chạy Test

### 1. Test với dữ liệu mẫu (pytest)
```bash
cd backend
pytest tests/ -v
```

### 2. Test với dữ liệu người dùng
```bash
cd backend
python3 /tmp/test_user_data.py
```

### 3. Test qua API
```bash
cd backend
python3 -m uvicorn app.main:app --reload --port 8000
# Mở http://localhost:8000/docs
# Gọi GET /api/findings?lang=vi
```

---

## Các Nguyên Lý Đối Soát Đã Áp Dụng

| § | Nguyên lý | Cách áp dụng |
|---|---|---|
| §3 | Đối soát nhiều nguồn | `_purchases()` lấy từ account + card; tri_source đối chiếu 3 nguồn |
| §4 | Công thức số dư | `Wallet.computed_balance_cents = opening + sum(events)` |
| §5 | Kiểm soát trùng | exact + fuzzy duplicate |
| §6 | Phân biệt sai lệch vs độ trễ | Confidence score |
| §7 | Kiểm tra vòng đời | no welcome, charged after cancel, free trial |
| §8 | Rule-based detection | Tất cả hàm với threshold cố định |
| §9 | Trend / outlier | spending_spike, category_concentration |
| §10 | Drill-down | Mọi finding có sources → từng txn |
| §12 | Vòng đời cảnh báo | NEW → CONFIRMED → RESOLVED |
| §13 | Chống cảnh báo trùng | fingerprint SHA256 |
| §14 | Ưu tiên xử lý | Sort theo label + amount |

---

## Mở Rộng (Adding New Rules)

1. Thêm `FindingKind` trong `models.py`
2. Thêm label mapping trong `labels.py`
3. Viết hàm detection trong `anomaly.py`
4. Thêm vào orchestrator `detect()`
5. Thêm reason fields trong `dedupe.py`
6. Thêm i18n trong `vi.json` / `en.json`
