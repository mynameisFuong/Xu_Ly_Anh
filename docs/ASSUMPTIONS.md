# Các giả định triển khai

- Giữ mô hình điểm danh lớp học: student, class và class session.
- Bản demo chạy local trên Windows, SQLite và một camera cho mỗi máy trạm.
- Web/desktop dùng bearer token có hạn; camera worker dùng camera token riêng.
- Engine Face ID là ageitgey/face_recognition + dlib ResNet 128D; OpenCV histogram
  là fallback demo và không hỗ trợ đăng ký đa góc.
- Ảnh chứng cứ và ảnh đăng ký lưu cục bộ trong storage; API kiểm tra quyền truy cập.
- Liveness/PAD và thử thách quay đầu đã được gỡ theo yêu cầu 30/10/2026.
  Nhận diện hiện tại không kiểm chứng chống ảnh in/video phát lại.
- Enrollment vẫn cần đủ năm góc và cùng profile preprocessing với điểm danh.
- YuNet hỗ trợ HOG khi detector mất mặt; chưa khẳng định cải thiện độ chính xác
  trước khi benchmark trên camera thực tế.
- State xác nhận nhiều frame của worker hiện ở RAM một process. Triển khai nhiều
  process phải có chiến lược định tuyến/store chung nếu cần duy trì chuỗi xác nhận.
- V3 là profile mặc định cho cả đăng ký và nhận diện (`enforce`). V1/v2 còn trong
  code để đối chiếu học thuật nhưng không dùng chung vector với gallery v3.
