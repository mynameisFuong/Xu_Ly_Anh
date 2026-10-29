# Các giả định triển khai

- Giữ mô hình điểm danh lớp học của hệ thống hiện tại; ánh xạ `employee` trong đặc tả tham chiếu thành `student`, `shift` thành `class session`.
- Bản demo chạy local trên Windows, một cơ sở đào tạo, một camera cho mỗi máy trạm và SQLite để dễ trình diễn.
- Quản trị viên demo có `X-User-Id=1`; cơ chế này chỉ dành cho demo nội bộ, không phải cấu hình production.
- `ageitgey/face_recognition` với dlib ResNet là engine Face ID đa góc. OpenCV histogram chỉ là dự phòng cho bản demo cũ và không tham gia đăng ký đa góc.
- Ảnh minh chứng và ảnh đăng ký được lưu cục bộ trong `storage/`, chỉ người có quyền quản trị/giảng viên được truy cập qua API.
- Web mới dùng PAD + thử thách ngẫu nhiên do server xác minh. Webcam RGB/CPU và
  khung 640×480 là môi trường thử nghiệm ban đầu. Không có tập dữ liệu thực địa
  được cấp phép trong repo nên chưa xác nhận APCER/BPCER hay khả năng chống deepfake.
- Có thể dùng bộ MiniFASNet pretrained đã kiểm checksum để thử local khi chủ động
  bật `LIVENESS_ALLOW_PRETRAINED`; không tự coi model đó đã được đánh giá/duyệt.
- MVP chạy một process backend cho state thử thách. Scale nhiều process phải dùng
  store dùng chung có TTL và thao tác consume nguyên tử trước khi nghiệm thu.
- Người dùng phản ánh mất mặt khoảng 30% khi quay đầu; đây là quan sát, chưa có
  mẫu camera để đo độc lập. Bổ sung YuNet hỗ trợ HOG và phục hồi frame mất mặt
  ngắn; không khẳng định tỷ lệ bỏ sót mới trước khi thử trên webcam thực tế.
