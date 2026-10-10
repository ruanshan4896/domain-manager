# Domain Manager 🚀
> Hệ thống backend Python tự động theo dõi thời hạn tên miền 24/7, tự động tra cứu WHOIS/RDAP, đồng bộ hai chiều với Google Sheets và gửi cảnh báo hết hạn qua Telegram Bot kèm tag người sở hữu và nút liên kết trực tiếp tới nhà đăng ký.

---

## 🏗️ Cấu Trúc Thư Mục Dự Án

```text
domain-manager/
├── core/                       # ⚙️ Tầng cấu hình và tiện ích dùng chung
│   ├── __init__.py
│   ├── config.py               # Cấu hình môi trường (.env), validation, logging
│   └── notifier.py             # Telegram Notifier gửi thông báo nhắc hạn kèm tag tên
│
├── renewals/                   # 🔔 Module Quản lý Gia Hạn Tên Miền
│   ├── __init__.py
│   ├── lookup.py               # Engine tra cứu RDAP ICANN/CentralNic & Socket WHOIS / WHOIS.com
│   ├── sheet.py                # Quản lý tab Domain_Renewals trên Google Sheets (Batch API)
│   └── service.py              # Xử lý chu kỳ kiểm tra gia hạn & phân loại Alert Stages
│
├── main.py                     # 🚀 Daemon Orchestrator điều phối chạy ngầm 24/7 hoặc chạy lẻ
├── Dockerfile                  # Dockerfile tối ưu (Python 3.12 slim, timezone Asia/Ho_Chi_Minh)
├── docker-compose.yml          # Cấu hình Docker Compose cho VPS aaPanel
├── requirements.txt            # Danh sách thư viện phụ thuộc
├── service_account.json        # Google Cloud Service Account credentials (tự cung cấp)
├── .env.example                # File mẫu cấu hình môi trường
└── .env                        # Biến môi trường hệ thống (bảo mật, không commit lên git)
```

---

## 📌 Tính Năng Nổi Bật

- 🔍 **Tra cứu tự động (Auto-Lookup):** Chỉ cần nhập tên miền vào tab `Domain_Renewals` (Cột A), bot tự động tra cứu ngày hết hạn và nhà đăng ký qua **Port 43 Socket WHOIS**, **RDAP (ICANN / CentralNic)** & **WHOIS.com**.
- 👤 **Hỗ trợ Tag Chủ Sở Hữu (Telegram Mentions):** Thêm cột `Owner / Telegram` (Cột B), Bot tự động tag trực tiếp username của chủ tên miền khi đến hạn.
- 🔔 **Cảnh báo đúng lúc (2 mốc chuẩn):**
  - **Lần 1:** Đúng ngày hết hạn (0 ngày còn lại).
  - **Lần 2:** Ngày hôm sau để nhắc nhở khẩn cấp (quá hạn 1 ngày).
  - **Nội dung thông báo:** 
    `Tên miền {domain} của @{owner} đã hết hạn, @daudepzai gia hạn giúp anh với em`
- ⚡ **Tối ưu Google Sheets API (Batch Operations):** Đọc toàn bộ danh sách và cập nhật các dòng thay đổi bằng batch update chỉ với 1 request duy nhất, không lo bị nghẽn quota.
- 🔄 **Tự động Reset:** Khi bạn gia hạn thành công tên miền và ngày hết hạn mới được cập nhật, trạng thái cảnh báo tự động trở về `PENDING`.

---

## 📊 Quy Tắc Thao Tác Trên Google Sheet

Tab làm việc mặc định: **`Domain_Renewals`**

| Cột | Tên Cột | Mô tả & Lưu ý |
|---|---|---|
| **A** | `Domain` | **Bắt buộc**: Tên miền cần theo dõi (ví dụ: `example.com`). |
| **B** | `Owner / Telegram` | Username Telegram người sở hữu (ví dụ: `@username` hoặc `username`). Bot sẽ tag tên này khi gửi cảnh báo. |
| **C** | `Expiry Date` | Ngày hết hạn định dạng `YYYY-MM-DD`. Bot tự động điền khi tra cứu được. Bạn có thể tự gõ tay nếu là đuôi tên miền đặc thù. |
| **D** | `Registrar` | Nhà đăng ký (Namecheap, Cloudflare, GoDaddy...). Bot tự điền hoặc bạn tự nhập. |
| **E** | `Auto Renew` | Trạng thái tự động gia hạn (`YES` hoặc `NO`). |
| **F** | `Days Left` | Số ngày còn lại (Bot tự tính và hiển thị ví dụ: `15 ngày` hoặc `Quá hạn 1 ngày`). |
| **G** | `Alert Status` | Trạng thái gửi cảnh báo (`PENDING`, `ALERT_0D`, `ALERT_EXPIRED`). |
| **H** | `Status` | Trạng thái hoạt động: `ACTIVE`, `EXPIRED`, hoặc `PAUSED` (nếu đặt `PAUSED`, bot sẽ bỏ qua không kiểm tra). |

> [!TIP]
> - **Cột I trở đi:** Bạn có thể tự do thêm cột (ghi chú, giá tiền gia hạn, thẻ thanh toán...) mà không ảnh hưởng tới code.
> - **Format hiển thị:** Thoải mái chỉnh màu nền, font chữ, độ rộng cột, viền bảng.

---

## 💻 Các Lệnh CLI Hỗ Trợ

```bash
# Chạy daemon 24/7 kiểm tra định kỳ mỗi ngày
python main.py

# Chạy một chu kỳ kiểm tra duy nhất rồi thoát ngay
python main.py --once

# Kiểm tra kết nối Telegram Bot
python main.py --test-telegram

# Kiểm tra tính hợp lệ của cấu hình & Service Account JSON
python main.py --validate-only
```

---

## 🛠️ Triển Khai Lên VPS aaPanel (Docker & Git)

1. **Clone mã nguồn từ GitHub:**
   ```bash
   cd /www/wwwroot
   git clone https://github.com/ruanshan4896/domain-manager.git
   cd domain-manager
   ```

2. **Cấu hình file `.env` và `service_account.json`:**
   - Copy file mẫu cấu hình:
     ```bash
     cp .env.example .env
     ```
   - Chỉnh sửa thông tin Telegram Bot token, Chat ID, Google Sheet Name trong `.env`.
   - Upload file `service_account.json` của Google Cloud vào thư mục `domain-manager`.

3. **Khởi chạy container với Docker Compose:**
   ```bash
   docker compose up -d --build
   ```

4. **Xem log hoạt động:**
   ```bash
   docker compose logs -f
   ```

5. **Cập nhật code khi có phiên bản mới:**
   ```bash
   git pull origin main
   docker compose up -d --build
   ```
