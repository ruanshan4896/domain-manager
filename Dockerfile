# Sử dụng Python slim image tối ưu dung lượng
FROM python:3.12-slim

# Thiết lập biến môi trường Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TZ=Asia/Ho_Chi_Minh

# Cài đặt timezone data
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy file requirements và cài đặt dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn
COPY . .

# Khởi chạy daemon theo dõi gia hạn tên miền
CMD ["python", "main.py"]
