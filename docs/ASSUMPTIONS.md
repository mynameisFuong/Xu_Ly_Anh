# Các giả định triển khai

- Giữ mô hình điểm danh lớp học của hệ thống hiện tại; ánh xạ `employee` trong đặc tả tham chiếu thành `student`, `shift` thành `class session`.
- Bản demo chạy local trên Windows, một cơ sở đào tạo, một camera cho mỗi máy trạm và SQLite để dễ trình diễn.
- Quản trị viên demo có `X-User-Id=1`; cơ chế này chỉ dành cho demo nội bộ, không phải cấu hình production.
- `ageitgey/face_recognition` với dlib ResNet là engine Face ID đa góc. OpenCV histogram chỉ là dự phòng cho bản demo cũ và không tham gia đăng ký đa góc.
- Ảnh minh chứng và ảnh đăng ký được lưu cục bộ trong `storage/`, chỉ người có quyền quản trị/giảng viên được truy cập qua API.
