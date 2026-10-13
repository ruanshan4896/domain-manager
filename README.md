# Domain Manager 🚀
> Hệ thống backend Python tự động theo dõi thời hạn tên miền và kiểm tra HTTP Status Code 24/7, tự động tra cứu WHOIS/RDAP và đồng bộ trực tiếp lên Google Sheets (hoạt động độc lập, tập trung hiển thị trực quan trên Google Sheet, không gửi thông báo Telegram).

---

## 🏗️ Cấu Trúc Thư Mục Dự Án

```text
domain-manager/
├── core/                       # ⚙️ Tầng cấu hình và tiện ích dùng chung
│   ├── __init__.py
│   ├── config.py               # Cấu hình môi trường (.env), validation, logging
│   └── notifier.py             # Tiện ích gửi thông báo (tuỳ chọn)
│
├── renewals/                   # 🔔 Module Quản lý Gia Hạn Tên Miền
│   ├── __init__.py
│   ├── lookup.py               # Engine tra cứu RDAP ICANN/CentralNic & Socket WHOIS / WHOIS.com
│   ├── sheet.py                # Quản lý tab Domain_Renewals trên Google Sheets (Batch API)
│   └── service.py              # Xử lý chu kỳ kiểm tra gia hạn & cập nhật Google Sheet
│
├── statuscode/                 # 🌐 Module Kiểm Tra HTTP Status Code
│   ├── __init__.py
│   ├── checker.py              # Kiểm tra mã HTTP trực tiếp (không follow redirects)
│   ├── sheet.py                # Quản lý tab Statuscode trên Google Sheets
│   └── service.py              # Chu kỳ kiểm tra 10 phút & cập nhật Google Sheet
│
├── main.py                     # 🚀 Daemon Orchestrator điều phối chạy ngầm 24/7 hoặc chạy lẻ
├── Dockerfile                  # Dockerfile tối ưu (Python 3.12 slim, timezone Asia/Ho_Chi_Minh)
├── docker-compose.yml          # Cấu hình Docker Compose cho VPS aaPanel
├── requirements.txt            # Danh sách thư viện phụ thuộc
├── service_account.json        # Google Cloud Service Account credentials (bắt buộc)
├── .env.example                # File mẫu cấu hình môi trường
└── .env                        # Biến môi trường hệ thống (bảo mật, không commit lên git)
```

---

## 📌 Tính Năng Nổi Bật

### 1. Quản Lý Gia Hạn Tên Miền (Mỗi ngày 1 lần)
- 🔍 **Tra cứu tự động (Auto-Lookup):** Nhập tên miền vào tab `Domain_Renewals` (Cột A), hệ thống tự tra cứu ngày hết hạn qua **RDAP (ICANN / CentralNic)**, **Socket WHOIS Port 43** & **WHOIS.com**. Hỗ trợ đặc biệt cho ccTLD như `.ws`, v.v.
- ⚡ **Tự tính ngày còn lại (Days Left):** Cột C tự động hiển thị số ngày còn lại (ví dụ: `15 ngày` hoặc `Quá hạn 1 ngày`).

### 2. Giám Sát HTTP Status Code (Mỗi 10 phút 1 lần)
- 🌐 **Kiểm tra trạng thái HTTP:** Ping kiểm tra mã phản hồi trực tiếp (không chuyển hướng để ghi nhận đúng mã ban đầu như `200`, `301`, `403`, `404`, `5xx`).
- ⚡ **Cập nhật gọn gàng vào Google Sheet:** Tự động ghi mã số (ví dụ: `200`, `301`, `404`, `500`) vào Cột B tab `Statuscode`.
- 🔇 **Không phiền toái:** Toàn bộ dữ liệu hiển thị tập trung trên Google Sheet, không gửi tin nhắn Telegram.

---

## 📊 Quy Tắc Thao Tác Trên Google Sheet

### Tab 1: `Domain_Renewals` (Theo dõi hạn tên miền)
| Cột | Tên Cột | Mô tả & Lưu ý |
|---|---|---|
| **A** | `Domain` | **Bắt buộc**: Tên miền cần theo dõi. Đặt `#` ở đầu để tạm ngưng. |
| **B** | `Expiry Date` | Ngày hết hạn `YYYY-MM-DD`. Bot tự điền hoặc có thể tự nhập tay. |
| **C** | `Days Left` | Số ngày còn lại (Bot tự tính ví dụ: `15 ngày` hoặc `Quá hạn 1 ngày`). |

### Tab 2: `Statuscode` (Kiểm tra HTTP Status Code)
| Cột | Tên Cột | Mô tả & Lưu ý |
|---|---|---|
| **A** | `Domain` | **Bắt buộc**: Tên miền cần kiểm tra trạng thái HTTP. Đặt `#` ở đầu để bỏ qua. |
| **B** | `Status Code` | Mã phản hồi HTTP (Bot tự điền mã số: `200`, `301`, `403`, `404`, `500`...). |

---

## 💻 Các Lệnh CLI Hỗ Trợ

```bash
# Chạy daemon 24/7 (Kiểm tra Status Code mỗi 10 phút, kiểm tra hạn tên miền mỗi 24h)
python main.py

# Chạy một chu kỳ đầy đủ (cả Statuscode & Renewals) rồi thoát
python main.py --once

# Chỉ chạy kiểm tra Status Code một lần rồi thoát
python main.py --check-statuscode

# Chỉ chạy kiểm tra Gia Hạn tên miền một lần rồi thoát
python main.py --check-renewals

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
   - Chỉnh sửa thông tin Google Sheet Name trong `.env`.
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
