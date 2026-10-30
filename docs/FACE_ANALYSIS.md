# Tiền xử lý ảnh và nhận diện khuôn mặt

Liveness/PAD đã được gỡ khỏi hệ thống theo yêu cầu ngày 30/10/2026.
Điểm danh web/desktop gửi ảnh trực tiếp để nhận diện, không còn thử thách quay đầu
hoặc yêu cầu model chống giả mạo. Kế hoạch nâng cấp thuật toán mới nằm trong
[PREPROCESSING_UPGRADE_PLAN.md](PREPROCESSING_UPGRADE_PLAN.md).

## Pipeline hiện tại

Ảnh bytes → BGR uint8 (EXIF đúng một lần) → xác định hướng/tìm các mặt → từng ROI
được kiểm tra chất lượng pixel gốc và tiền xử lý cùng profile → embedding dlib
128D → so khớp gallery của lớp → xác nhận riêng từng người qua nhiều frame →
ghi điểm danh và tiếp tục nhận diện. Pose vẫn phục vụ bước đăng ký năm góc.

[preprocessing.py](../ai_pipeline/preprocessing.py) chứa biến đổi thuần và ma trận
tọa độ. [analysis.py](../ai_pipeline/analysis.py) điều phối; kết quả face_box luôn
theo ảnh nguồn. [recognition.py](../ai_pipeline/recognition.py) giữ hợp đồng
EmbeddingResult; [quality.py](../ai_pipeline/quality.py) vẫn từ chối ảnh nguồn
quá nhỏ/tối/sáng/nhòe. Đăng ký mẫu vẫn từ chối nhiều mặt; luồng điểm danh stream
xử lý mỗi khuôn mặt độc lập, không để một ảnh mờ chặn những người khác.

## Cấu hình

- PREPROCESSING_MODE=off: giữ luồng legacy.
- PREPROCESSING_MODE=shadow: giữ quyết định legacy, đo thử nhánh preprocessing.
- PREPROCESSING_MODE=enforce: dùng preprocessing và ghép profile vào model_version.
- PREPROCESSING_ALIGN_EYES=true và PREPROCESSING_NORMALIZE_LIGHTING=true bật
  căn mắt và CLAHE ở v1. Mirror chỉ bật khi biết pixel đầu vào thực sự bị lật.
- PREPROCESSING_SEARCH_ROTATIONS/PREPROCESSING_SEARCH_ROLLS hỗ trợ tìm hướng.
- FACE_DETECTION_BACKEND chọn hog, hybrid hoặc yunet. YuNet tải bằng
  [download_face_detector.py](../scripts/download_face_detector.py); thiếu model
  thì fallback về HOG.
- PREPROCESSING_VERSION=v1 giữ profile cũ. V2 ưu tiên căn chỉnh nội bộ của dlib,
  chọn gamma HOẶC CLAHE theo độ sáng/tương phản của mặt, giữ ảnh tốt nguyên trạng.
  PREPROCESSING_V2_ALIGN_EYES=true chỉ để đo ablation căn roll ngoài; các ma trận
  được hợp nhất để render lại từ pixel nguồn thay vì nội suy nhiều lần.
- PREPROCESSING_DENOISE_METHOD=off mặc định. `adaptive` chọn median 3×3 theo
  tỷ lệ nhiễu xung hoặc bilateral nhỏ theo MAD high-pass ở vùng ít gradient.
  Các ước lượng này là heuristic có thể nhầm texture; chỉ bật khi benchmark có lợi.
- PREPROCESSING_MAX_DETECTION_ATTEMPTS=8 giới hạn số lần gọi detector ở v2,
  gồm hướng gốc, 90/180/270 và roll ±20/±40 trong giới hạn cấu hình.
- PREPROCESSING_SHADOW_V2=true và PREPROCESSING_SHADOW_SAMPLE_RATE=0.1 chạy
  đối chiếu v2 trên 10% lượt v1 enforce; giữ embedding, pose, box và quyết định v1.
  Chế độ shadow thường giữ legacy chưa preprocessing, còn enforce v1 + shadow_v2
  dùng v1 làm đối chứng. Đặt sample_rate=0 để tắt chi phí đối chiếu.

Các khóa cũ LIVENESS_* và WEB_LIVENESS_* được bỏ qua để tệp môi trường cũ vẫn
khởi động. Chúng không thể bật lại chức năng đã gỡ. ONNX Runtime không còn là
dependency bắt buộc; file model/dataset cũ trong storage không được nạp.

## Đăng ký và vận hành

Enrollment, scan-frame và camera worker phải dùng cùng profile. Khi đổi tham số
ảnh hưởng embedding, đăng ký lại đủ năm góc của profile mới; không trộn mẫu cũ.
Chỉ gỡ liveness trong lần này không thay profile preprocessing hay embedding.

Web/desktop/worker mới dùng stream nhiều mặt, giữ video chạy và không yêu cầu
bấm người tiếp theo. Mỗi mặt có khung vàng riêng khi chờ, khung xanh + tên/MSSV
khi server đã lưu điểm danh. Mỗi người được ghi một lần trong buổi; log giao
diện cũng không lặp lại mỗi frame. Các box rời khung được xóa ở kết quả tiếp theo;
overlay quá 1,5 giây không có cập nhật bị bỏ. Kiểm tra thay đổi pixel vùng mặt
ẩn tên/màu xanh cũ khi ảnh live khác ảnh vừa phân tích; phép này chỉ bỏ overlay,
không xác nhận danh tính và không quyết định ghi điểm danh.

Xem [STREAM_RECOGNITION.md](STREAM_RECOGNITION.md) về giới hạn CPU, cửa sổ xác
nhận, chống trùng frame và cách test người vào/rời camera.

Web đăng ký năm góc phát tít ngắn 90 ms mỗi 650 ms khi đang chờ; sau mỗi góc
được server ghi nhận, phát tít dài 650 ms và nghỉ hai giây để đổi hướng. Có
checkbox bật/tắt âm thanh. Âm thanh được mở từ thao tác bấm bắt đầu, không cần
quyền microphone. Dừng quét, đổi trang, lỗi request hoặc ẩn tab sẽ dừng tiếng
tít; phản hồi cũ sau khi dừng không được đổi góc hay phát tiếng thành công.
Nếu trình duyệt không hỗ trợ phát âm thanh, hướng dẫn bằng chữ vẫn hoạt động.

Desktop gửi scan-stream. Worker dùng camera token, hỏi camera/pipeline rồi gửi
camera-scan-stream nếu backend hỗ trợ, kể cả preprocessing off. Việc gửi ảnh
được tách khỏi luồng hiển thị camera; vẫn chỉ có một frame đang xử lý cho mỗi
stream và hỗ trợ dry_run không ghi DB. API scan-frame cũ còn để tương thích.
Xem hợp đồng tại [API.md](API.md).

Khởi động local trên máy đã có môi trường Python 3.13:

```powershell
.\.venv313\Scripts\python.exe scripts/run_web.py --reload
```

Dừng backend cũ trước khi chạy lại; tải lại trang để nhận JavaScript mới.
Launcher local đọc lại .env hiện tại và đặt thư mục làm việc về gốc dự án.

## Kiểm tra

```powershell
.\.venv313\Scripts\python.exe -m pytest -q --run-browser
.\.venv313\Scripts\python.exe -m ruff check .
```

Nhóm browser dùng Chrome headless và webcam tổng hợp. Các unit test tọa độ,
dtype và fallback không thay thế benchmark accuracy trên camera thật. Các
nâng cấp v2 đã được cài đặt, có kiểm thử tọa độ, EXIF, nhánh chất lượng và fallback.
Retinex/Tan–Triggs chỉ có ở công cụ benchmark, không chọn được qua cấu hình runtime.
Xem [PREPROCESSING_BENCHMARK.md](PREPROCESSING_BENCHMARK.md) để đo và chuyển profile.
