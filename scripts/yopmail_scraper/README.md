# YOPmail Scraper Tool (Full Content & Header Extraction)

Tool cào dữ liệu email từ bất kỳ tài khoản YOPmail nào (mặc định: `wealifytester@yopmail.com`), hỗ trợ bóc tách đầy đủ **Nội dung HTML, Plain Text, Link kích hoạt và Mã xác thực OTP**.

---

## 📌 1. Tại sao cần Trình duyệt (Puppeteer) để lấy Content?
YOPmail áp dụng cơ chế bảo vệ Google reCAPTCHA v2 trên endpoint đọc chi tiết email (`#ifmail`). Khi gọi bằng HTTP request thuần (`easy-yopmail`), máy chủ YOPmail sẽ trả về trang chặn: *"Complete the CAPTCHA to continue"*.

Vì vậy, tool cung cấp 2 chế độ:
- **Chế độ Full Content (`scrape_full.js`)**: Dùng Puppeteer tự động mở giao diện trình duyệt, điều hướng qua các iframe (`#ifinbox` và `#ifmail`), chỉ cần giải CAPTCHA 1 lần đầu tiên (nếu có), sau đó tool sẽ tự động quét và bóc tách toàn bộ 100% nội dung (HTML + Plain Text + OTP) của tất cả các email.
- **Chế độ Fast Headers (`scrape.js`)**: Sử dụng HTTP API để cào siêu nhanh toàn bộ danh sách email (ID, Tiêu đề, Người gửi, Ngày giờ) trong vài giây mà không cần mở trình duyệt.

---

## 🚀 2. Cài đặt & Hướng dẫn sử dụng

### Bước 1: Cài đặt thư viện
```bash
cd scripts/yopmail_scraper
npm install
```

### Bước 2: Cào TOÀN BỘ NỘI DUNG Email (HTML + Plain Text + OTP)
```bash
npm run scrape:full
```
*(Cửa sổ Chromium sẽ mở ra. Nếu YOPmail hiển thị CAPTCHA "I'm not a robot", bạn chỉ cần click chọn 1 lần. Tool sẽ tự động duyệt qua tất cả các trang và bóc tách toàn bộ email vào ổ đĩa).*

Hoặc chạy lệnh tùy chỉnh tham số:
```bash
node scrape_full.js --user wealifytester --limit 0 --delay 800
```
- `--user <tên_hòm_thư>`: Tên hòm thư YOPmail (mặc định `wealifytester`)
- `--limit <số_lượng>`: Số lượng email cần lấy (0 = lấy tất cả)
- `--delay <ms>`: Khoảng nghỉ giữa các email (mặc định `800` ms để an toàn)
- `--headless true`: Chạy ẩn không mở cửa sổ giao diện

### Bước 3: Cào NHANH DANH SÁCH Header (Không mở trình duyệt)
```bash
npm run scrape:headers
```

---

## 4. Chạy cron và ghi vào Postgres

Repo có sẵn pipeline một lần tại `scripts/yopmail_cron.sh`: chạy full scraper
headless, sau đó import `emails_full.json` vào bảng `emails`. Dữ liệu gốc cũng
được lưu trong `dataset_imports`, `dataset_files` và `dataset_rows`; email được
upsert theo `(mailbox, message_id)` nên chạy lại không tạo bản ghi trùng.

Chuẩn bị một lần:

```bash
cd /path/to/WLF-01-Nexa/scripts/yopmail_scraper
npm install
cd /path/to/WLF-01-Nexa
mkdir -p backend/logs
chmod +x scripts/yopmail_cron.sh
```

Chạy thử thủ công:

```bash
YOPMAIL_USER=wealifytester YOPMAIL_MAILBOX=tester \
NODE_BIN=/opt/homebrew/bin/node \
./scripts/yopmail_cron.sh
```

Thêm vào crontab, ví dụ chạy mỗi giờ ở phút 10:

```cron
10 * * * * cd /path/to/WLF-01-Nexa && YOPMAIL_USER=wealifytester YOPMAIL_MAILBOX=tester NODE_BIN=/opt/homebrew/bin/node ./scripts/yopmail_cron.sh >> /path/to/WLF-01-Nexa/backend/logs/yopmail-cron.log 2>&1
```

`NEXA_DATABASE_URL` được đọc từ `.env` như các lệnh backend khác. Cron cần
Postgres đang chạy và `backend/.venv` đã được tạo. Nếu YOPmail yêu cầu
reCAPTCHA, cron sẽ dừng trước bước import để không ghi nội dung không đầy đủ;
cần mở khóa/duy trì session theo môi trường triển khai rồi chạy lại.

## 📂 5. Cấu trúc dữ liệu đầu ra

Kết quả được lưu tại thư mục `./output/<tên_user>/`:
```text
output/wealifytester/
├── emails_full.json       # Toàn bộ dữ liệu chi tiết JSON (Body text, links, OTP, html path)
├── emails_full.csv        # Bảng dữ liệu tổng hợp để mở trên Excel / Google Sheets
├── full_report.md         # Báo cáo đọc trực tiếp Markdown
└── html/                  # Thư mục chứa các file HTML nguyên bản của từng email
    ├── mail_001_xxx.html
    ├── mail_002_xxx.html
    └── ...
```
