# Quyết định kỹ thuật

## Giữ kiến trúc local-first cho bản demo

Hệ thống hiện có là FastAPI + SQLAlchemy + SQLite và đã có luồng nghiệp vụ lớp học hoàn chỉnh. Thay toàn bộ bằng PostgreSQL/Redis/MinIO/Next.js ngay trong bản demo sẽ làm tăng rủi ro vận hành mà không cải thiện trải nghiệm trình diễn. Vì vậy bản này giữ modular monolith, bổ sung dashboard và console web chuyên nghiệp. Các interface nghiệp vụ vẫn tách đủ rõ để nâng cấp hạ tầng sau.

## Dữ liệu sinh trắc học

Embedding và ảnh không được ghi ra log. Truy cập ảnh đi qua endpoint có phân quyền. Production phải dùng mã hóa volume, TLS, chính sách lưu giữ/xóa dữ liệu và PostgreSQL + pgvector như đặc tả.

## Nhận diện đa góc và chống giả mạo

Enrollment ưu tiên `ageitgey/face_recognition`, mô hình dlib ResNet 128 chiều và 68 facial landmarks. OpenCV `solvePnP` ước lượng yaw/pitch để bắt buộc thu đủ chính diện, trái, phải, lên và xuống. Realtime so sánh Euclidean với toàn bộ pose template của mỗi người, sau đó kiểm tra ngưỡng và margin với người thứ hai. Engine histogram cũ chỉ là fallback tương thích và không được phép chạy wizard đa góc.

Pipeline vẫn kiểm tra một khuôn mặt, kích thước, độ sáng, độ mờ, nhiều khung hình và idempotency. Liveness chuyên dụng chưa được giả lập bằng UI; production phải tích hợp MiniFASNet/ONNX trước khi nghiệm thu chống ảnh in/video phát lại.
