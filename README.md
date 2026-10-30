# AttendAI — điểm danh bằng khuôn mặt

Bản demo học thuật chạy local: quản lý sinh viên/lớp/buổi học, đăng ký khuôn mặt
năm góc, nhận diện nhiều người liên tục qua camera, điều chỉnh điểm danh và xuất
báo cáo. Backend FastAPI + SQLite; nhận diện dùng `face_recognition`/dlib 128D.

**Phạm vi:** hệ thống không có liveness/PAD và chưa chứng minh chống ảnh in hay
video phát lại. Kết quả tự động cần người giám sát; độ chính xác và hiệu năng phải
đo với camera và người tham gia thực tế. Không đưa ảnh hay vector khuôn mặt vào Git.

## Cài đặt và chạy demo trên Windows

Từ thư mục dự án vừa clone/pull, với Python 3.13 chính thức và PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe scripts/init_db.py
.\.venv\Scripts\python.exe scripts/seed_demo.py
.\.venv\Scripts\python.exe scripts/run_web.py --reload
```

Mở `http://127.0.0.1:8000/demo`. Tài khoản mới do seed tạo: `admin/admin123`,
`teacher/teacher123`, `device01/device123`. Nếu tài khoản đã tồn tại, seed giữ
nguyên mật khẩu hiện có. Các mật khẩu này chỉ dành cho demo local.

Seed tạo dữ liệu giả lập có tiền tố `[DEMO]`/`DEMO`: ba lớp, 12 sinh viên, ba
buổi đã đóng với trạng thái đúng/trễ/vắng giả lập và tối đa hai buổi đang mở.
Mỗi buổi mở có hai bản ghi mẫu đúng giờ/trễ và các sinh viên còn lại chờ điểm danh.
Giờ vào học buổi mở là 30 phút trước lúc seed; buổi lịch sử có ngày cố định.
Các bản ghi mẫu được gắn nguồn thủ công, không phải kết quả nhận diện thật. Chạy lại không ghi đè
hồ sơ, mật khẩu hay điểm danh đã có; mã trùng với dữ liệu không thuộc seed được
bỏ qua. Trước buổi demo, cập nhật giờ vào học cho phù hợp; nếu đã đóng buổi mẫu,
mở buổi mới trên giao diện khi muốn tiếp tục demo.

Seed **không tạo hay tải ảnh, embedding hoặc Face ID**. Để demo nhận diện, cài
engine bên dưới và đăng ký người tham gia đồng ý sử dụng ảnh qua camera trên máy
đó. Không có mẫu, hệ thống vẫn cho xem danh sách và điểm danh thủ công.

### Cài Face ID trên Windows

Sau khi tạo `.venv`, chạy trong PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_faceid.ps1
```

Script cài `dlib-bin`, model và `face_recognition`, rồi kiểm tra engine. Trên macOS
Apple Silicon, xem và chạy `bash scripts/install_faceid.sh` trong virtualenv.
Khi thiếu dlib, ứng dụng vẫn có thể dùng tính năng quản lý/điểm danh thủ công,
nhưng API điểm danh bằng Face ID và đăng ký năm góc không dùng histogram dự phòng.

## Luồng demo

1. **Sinh viên:** xem dữ liệu `[DEMO]`, tìm kiếm, chỉnh sửa hoặc nhập CSV/XLSX có
   xem trước; chọn lớp ghi danh và trạng thái đồng ý.
2. **Khuôn mặt:** chọn sinh viên đã đồng ý, quét lần lượt chính diện, trái, phải,
   lên, xuống. Tít ngắn là đang chờ; tít dài là góc đã nhận. Bộ mẫu cũ tiếp tục
   hoạt động nếu quét lại chưa hoàn tất. Face ID chỉ được dùng trong buổi điểm danh
   của lớp học mà sinh viên đã ghi danh. Màn hình Khuôn mặt hiển thị các lớp này và
   cho phép ghi danh thêm vào đúng lớp mà không cần quét lại.
3. **Buổi học:** chọn một buổi đang mở hoặc tạo buổi mới. Trong **Điểm danh**,
   xem cảnh báo số sinh viên đã có Face ID, bật camera và bắt đầu quét một lần.
   Vàng là đang chờ; xanh kèm tên là đã lưu. Người khác có thể tiếp tục vào khung.
4. Xem bảng; điều chỉnh thủ công với lý do; đóng buổi để đánh dấu vắng những người
   chưa có bản ghi. Giao diện web xuất CSV; API cũng có endpoint xuất XLSX.

Thời gian được lưu/trao đổi theo UTC và hiển thị theo múi giờ trình duyệt. Với
buổi đã từng bị chỉnh bởi phiên bản cũ, kiểm tra lại giờ vào học trước khi demo.

## Chuyển dữ liệu nghiệp vụ giữa các máy

Git **không tự đồng bộ cơ sở dữ liệu local**. Máy mới pull code rồi chạy seed sẽ
có dữ liệu giả lập; dữ liệu do người dùng tự tạo ở máy cũ cần chuyển riêng.

Trên máy nguồn, xuất metadata vào đường dẫn chưa tồn tại:

```powershell
.\.venv\Scripts\python.exe scripts/transfer_metadata.py export storage/portable/metadata.json
```

Chuyển file JSON đó sang máy đích bằng phương thức bạn chọn. Sau khi máy đích đã
chạy `init_db.py` và `seed_demo.py`, nhập bằng đường dẫn đến file đã chuyển:

```powershell
.\.venv\Scripts\python.exe scripts/transfer_metadata.py import storage/portable/metadata.json
```

File gồm hồ sơ, lớp, ghi danh, buổi và bản ghi điểm danh; **không gồm ảnh,
embedding, ảnh minh chứng, mật khẩu, token, event nhận diện hay log audit gốc**.
Thông tin cá nhân trong metadata vẫn cần được bảo vệ. Nhập là bổ sung: mã sinh
viên/lớp đã có được giữ nguyên; bản ghi điểm danh đã có không bị ghi đè; nếu lớp
đích đã có buổi mở thì buổi mở xung đột bị bỏ qua và số lượng được báo. Khi không
có tài khoản giảng viên trùng, lớp mới được gán cho tài khoản `teacher` sẵn có
(hoặc chỉ định `--teacher TAI_KHOAN`). Không tự tạo mật khẩu của máy nguồn.
Không có mẫu nhận diện trên máy đích; phải đăng ký lại để quét khuôn mặt.

## Cấu hình và kiểm thử

`.env.example` mặc định bật `PREPROCESSING_MODE=enforce` và
`PREPROCESSING_VERSION=v3`. Detector HOG là mặc định trên máy mới; có thể dùng
`hybrid`/YuNet khi đã tải model. Mẫu Face ID của v1/v2 không được ghép với
embedding v3; cần đăng ký đủ năm góc trên máy mới. `run_web.py` đọc `.env` ở
thư mục dự án; khởi động lại sau khi chỉnh.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_ui.py --run-browser
```

Test browser dùng Chrome và webcam tổng hợp; không thay thế thử nghiệm người thật.
OpenAPI tại `http://127.0.0.1:8000/docs`. Có thể chạy desktop bằng
`python desktop_app/main.py` khi backend đã chạy; camera worker dùng token riêng.

## Tài liệu hệ thống

- [Mô tả hệ thống hiện hành](docs/SYSTEM.md): phạm vi, kiến trúc, thuật toán,
  nghiệp vụ, dữ liệu, giới hạn và gợi ý dẫn chứng cho báo cáo.
- [API](docs/API.md), [luồng stream nhiều mặt](docs/STREAM_RECOGNITION.md),
  [tiền xử lý và nhận diện](docs/FACE_ANALYSIS.md).
- [Phương pháp thử nghiệm đồ án](docs/THU_NGHIEM_DO_AN.md),
  [benchmark tiền xử lý](docs/PREPROCESSING_BENCHMARK.md),
  [đánh giá stream](docs/ATTENDANCE_RELIABILITY.md).
- [Giả định](docs/ASSUMPTIONS.md); [lịch sử quyết định](docs/DECISIONS.md).
  Một số tài liệu lịch sử còn nhắc PAD đã gỡ và không mô tả runtime hiện tại.

V3 hiện là profile hoạt động cho đăng ký và điểm danh. Công cụ xuất ảnh từng
bước cùng [benchmark tiền xử lý](docs/PREPROCESSING_BENCHMARK.md) hỗ trợ kiểm tra
chất lượng; chưa có phép đo trên nhiều người/camera đủ để khẳng định v3 luôn tốt hơn.
