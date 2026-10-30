# Bộ tài liệu dự án Face Attendance

Cập nhật theo mã nguồn ngày 31/10/2026. Đây là tài liệu sản phẩm/kỹ thuật để làm
căn cứ viết báo cáo, **không phải báo cáo môn học đã soạn sẵn**. Mã nguồn và
OpenAPI của phiên bản đang chạy là căn cứ khi tài liệu và cấu hình local khác nhau.
“V3” là phiên bản tiền xử lý ảnh, không phải model nhận diện tự huấn luyện mới.

## Thứ tự đọc

| Tài liệu | Nội dung và mục đích |
| --- | --- |
| [README dự án](../README.md) | Cài đặt, khởi động, dữ liệu demo, chuyển máy và lệnh test. |
| [Hướng dẫn người dùng](USER_GUIDE.md) | Thao tác từ đăng nhập đến xem buổi đã đóng; xử lý lỗi thường gặp. |
| [Mô tả hệ thống](SYSTEM.md) | Kiến trúc, phạm vi, phân quyền và các luồng chính. |
| [Mô hình dữ liệu](DATA_MODEL.md) | ERD, bảng, ràng buộc, vòng đời dữ liệu và giới hạn lịch sử. |
| [Thuật toán xử lý ảnh](IMAGE_PROCESSING.md) | Công thức, điều kiện áp dụng, đầu vào/đầu ra và nguồn học thuật. |
| [Điều phối nhận diện](FACE_ANALYSIS.md) | Chế độ off/shadow/enforce, đăng ký năm góc và các client. |
| [Stream nhiều mặt](STREAM_RECOGNITION.md) | Gallery lớp, track, xác nhận nhiều frame, overlay và hiệu năng. |
| [API](API.md) | Xác thực, endpoint, payload, lỗi và hợp đồng tương thích. |
| [Kiểm chứng phần mềm/UX](EVALUATION.md) | Những gì đã kiểm thử, sửa UX, giới hạn bằng chứng và phần cần đo. |
| [Thực nghiệm đồ án](THU_NGHIEM_DO_AN.md) | Thu mẫu và ghi số liệu camera/người thật. |
| [Benchmark tiền xử lý](PREPROCESSING_BENCHMARK.md) | Manifest, ablation, hiệu chỉnh validation và kiểm tra test. |
| [Độ tin cậy điểm danh](ATTENDANCE_RELIABILITY.md) | Xác nhận track, đo stream ngoại tuyến và giới hạn suy luận. |
| [Giả định](ASSUMPTIONS.md), [quyết định](DECISIONS.md) | Lý do chọn kiến trúc, cấu hình và phạm vi triển khai. |

## Tài liệu thiết kế hoặc lịch sử

- [Kế hoạch preprocessing](PREPROCESSING_UPGRADE_PLAN.md): kế hoạch gốc và bảng
  trạng thái triển khai; phần đánh giá ban đầu nói về v1, không thay mô tả v3.
- [Lựa chọn dữ liệu PAD](PAD_DATASET_SELECTION.md): nghiên cứu lịch sử; liveness,
  công cụ train/evaluate PAD và model loader đã gỡ, không dùng để vận hành.
- [Đặc tả gốc](../faceid-attendance-spec.md), [đề bài thiết kế](../prompt_solution.md):
  nguồn yêu cầu trước đây, có chức năng/công nghệ/chỉ tiêu chưa triển khai.
  Không coi các chỉ tiêu dự kiến là kết quả của sản phẩm hiện tại.

## Cách sử dụng làm căn cứ báo cáo

| Nội dung cần trình bày | Căn cứ nên dùng | Bằng chứng còn phải tự thu |
| --- | --- | --- |
| Bài toán, use case, phạm vi | SYSTEM, USER_GUIDE | Ảnh chụp giao diện trên máy demo, đã ẩn thông tin cá nhân. |
| Kiến trúc và CSDL | SYSTEM, DATA_MODEL, models.py | Phiên bản commit, cấu hình và sơ đồ phù hợp thực tế triển khai. |
| Xử lý ảnh học thuật | IMAGE_PROCESSING, preprocessing.py, quality.py | Ảnh trước/sau được phép chia sẻ; histogram/chỉ số chất lượng nếu đo. |
| Nhận diện và điểm danh | FACE_ANALYSIS, STREAM_RECOGNITION, API | Lượt người vào/rời camera, kết quả đúng/nhầm/bỏ sót và thời gian chờ. |
| Kiểm thử phần mềm | EVALUATION, thư mục tests | Đầu ra lệnh test của đúng commit và môi trường. |
| Đánh giá cải tiến v3 | THU_NGHIEM_DO_AN, PREPROCESSING_BENCHMARK | Bộ validation/test khác phiên và số liệu đối chiếu trên cùng dữ liệu. |

Phân biệt ba loại dữ liệu: seed giả lập để minh họa nghiệp vụ; test tổng hợp để
kiểm tra logic; dữ liệu camera thật để đánh giá chất lượng. Không thay thế chúng
cho nhau. Không dùng số liệu công bố của dlib hoặc kết quả test logic để tuyên bố
accuracy của toàn hệ thống. Repository không huấn luyện lại ResNet và không có PAD.

Các ảnh, embedding, DB local và báo cáo đo trong `storage/` không theo Git. Khi
trích kết quả đo local, lưu phiên bản mã, điều kiện, số người và phương pháp đo;
nếu thiếu artifact hoặc không tái lập được thì chỉ ghi là quan sát cũ.
