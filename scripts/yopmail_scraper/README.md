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

## 4. Chạy bên trong ứng dụng và cập nhật dataset

Backend tự đăng ký job APScheduler theo cấu hình `NEXA_YOPMAIL_*`, không cần
crontab của hệ điều hành. Job chạy full scraper headless rồi cập nhật file
`dataset/email_<mailbox>.csv`. Giai đoạn này chưa chạy migration và chưa ghi
Postgres.

Sau khi apply thành công, backend tự xóa JSON/CSV/report/HTML trung gian trong
`scripts/yopmail_scraper/output`; nếu crawl lỗi, output được giữ lại để debug.

Trước mỗi lần ghi, job tạo một backup timestamped ngay cạnh file dataset và
giữ lại mặc định. Nếu cần phục hồi:

```bash
cp dataset/email_tester.csv.backup-<timestamp> dataset/email_tester.csv
```

Chạy ngay qua API:

```bash
curl -X POST http://localhost:8000/api/monitor/yopmail
```

Mặc định job chạy mỗi `5 phút`. Có thể đổi trong `.env`, ví dụ:

```env
NEXA_YOPMAIL_ENABLED=true
NEXA_YOPMAIL_USERS=wealifytester,wealifyjunior,wealifysenior
NEXA_YOPMAIL_MAILBOXES=tester,junior,senior
NEXA_YOPMAIL_INTERVAL_MINUTES=5
NEXA_YOPMAIL_DATASET_DIR=./dataset
```

Nếu YOPmail yêu cầu reCAPTCHA, job sẽ dừng trước bước cập nhật dataset để không ghi
nội dung không đầy đủ.

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
