# Wealify Transactions & Sidebar Drawer Scraper

Công cụ tự động hoá thu thập toàn bộ **Lịch sử giao dịch** và **Chi tiết giao dịch trong Sidebar (Drawer)** từ cổng quản lý Wealify khi không có API công khai, sử dụng đăng nhập tài khoản/mật khẩu và hỗ trợ cơ chế chống bot (Stealth).

---

## 🌟 Tính năng nổi bật

1. **Xác thực an toàn & Quản lý Session:**
   - Đăng nhập bằng `username/password` với cơ chế mô phỏng gõ phím của con người.
   - Hỗ trợ lưu Cookie và `localStorage` vào thư mục `sessions/` — chạy các lần sau không cần nhập lại mật khẩu.
   - Hỗ trợ xử lý mã xác thực 2FA/OTP (nhập trực tiếp trên console hoặc tự động lấy từ YOPmail).
2. **Thu thập dữ liệu 2 tầng (Hybrid Scraper):**
   - **Network Interception:** Tự động bắt ngầm Token Authorization và các API JSON nội bộ khi trang tải để lấy dữ liệu gốc tốc độ cao.
   - **DOM & Sidebar Crawler:** Tự động duyệt từng hàng trên bảng, click để mở Sidebar Drawer, cào chi tiết (Gateway ID, MCC, Phí, Tỉ giá, Merchant), đóng Sidebar và chuyển trang.
3. **Bộ lọc & Phân trang thông minh:**
   - Hỗ trợ lọc theo khoảng ngày (`--date-from`, `--date-to`).
   - Giới hạn số trang cần cào (`--limit`).
4. **Định dạng xuất đa dạng:**
   - `output/transactions_full.json`: Giữ nguyên cấu trúc lồng nhau đầy đủ chi tiết của từng giao dịch (phù hợp nạp vào AI Nexa).
   - `output/transactions.csv`: Bảng phẳng để mở trên Microsoft Excel / Google Sheets.
   - `output/summary_report.md`: Báo cáo tóm tắt số lượng giao dịch, tổng tiền vào/ra.

---

## 🚀 Hướng dẫn cài đặt & Chạy

### 1. Cài đặt thư viện
Trong thư mục `scripts/wealify_scraper`:
```bash
npm install
```

### 2. Cấu hình tài khoản (Tùy chọn)
Tạo file `.env` từ file `.env.example`:
```bash
cp .env.example .env
```
Điền thông tin tài khoản của bạn:
```ini
WEALIFY_BASE_URL=https://app.wealify.com
WEALIFY_USERNAME=your_email@example.com
WEALIFY_PASSWORD=your_password
WEALIFY_HEADLESS=false
```

### 3. Các lệnh chạy thông dụng

#### A. Chạy ở chế độ có giao diện (Khuyên dùng cho lần đầu để quan sát/nhập OTP):
```bash
node index.js
```
Hoặc truyền trực tiếp tài khoản qua tham số dòng lệnh:
```bash
node index.js --user "user@domain.com" --pass "mypassword"
```

#### B. Chạy ngầm (Headless) cho server/cron job:
```bash
node index.js --headless true
```

#### C. Cào danh sách và chi tiết Thẻ ảo (Virtual Cards):
```bash
node scrape_cards.js
# Hoặc:
npm run scrape:cards
```

#### D. Cào danh sách và chi tiết Tài khoản ảo (Virtual Accounts):
```bash
node scrape_va.js
# Hoặc:
npm run scrape:va
```

#### E. Cào thử nghiệm giới hạn số trang:
```bash
node index.js --limit 2
```

#### E. Lọc giao dịch theo khoảng ngày cụ thể:
```bash
node index.js --date-from "01/08/2026" --date-to "20/08/2026"
```

#### E. Tắt cào chi tiết Sidebar nếu chỉ cần danh sách bảng (Tăng tốc độ):
```bash
node index.js --full-drawer false
```

---

## 📁 Cấu trúc thư mục

```
scripts/wealify_scraper/
├── index.js                   # Entrypoint chính
├── package.json               # Khai báo dependencies
├── .env.example               # Mẫu cấu hình môi trường
├── sessions/                  # Lưu trữ Cookie/Session sau khi login thành công
├── output/                    # Thư mục chứa dữ liệu xuất (JSON, CSV, MD)
└── src/
    ├── auth/
    │   ├── login.js           # Xử lý điền form login và OTP
    │   └── session.js         # Lưu & khôi phục Cookie
    ├── scraper/
    │   ├── drawer_scraper.js  # Click bảng & mở/đóng Sidebar Drawer
    │   ├── interceptor.js     # Lắng nghe Network API & Authorization Token
    │   └── pagination.js      # Chuyển trang & áp dụng bộ lọc ngày
    ├── parser/
    │   └── normalizer.js      # Chuẩn hoá ngày tháng, tiền tệ, số thẻ
    └── storage/
        ├── json_exporter.js   # Xuất file JSON (có merge tránh trùng)
        └── csv_exporter.js    # Xuất file CSV
```

---

## 🔒 Lưu ý bảo mật
- Thư mục `sessions/` và file `.env` đã được cấu hình trong `.gitignore` để không bao giờ bị lộ thông tin đăng nhập hoặc cookie phiên làm việc.
- Dữ liệu số thẻ luôn được che chỉ còn 4 số cuối (`last4`) trước khi xuất ra báo cáo.
