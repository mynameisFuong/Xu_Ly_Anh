# AttendAI — Hệ thống điểm danh bằng khuôn mặt

Hệ thống điểm danh lớp học local-first với giao diện quản trị chuyên nghiệp, nhận diện khuôn mặt qua webcam, quản lý sinh viên/Face ID, chốt đúng giờ–đi trễ–vắng và xuất báo cáo Excel/CSV.

## Điểm nổi bật của bản demo

- Dashboard vận hành: số sinh viên, độ phủ Face ID, lớp học, phiên đang mở và tỷ lệ tham dự.
- Kiosk điểm danh trực tiếp: camera, hướng dẫn chất lượng, nhận diện liên tục và bảng kết quả realtime.
- Tiếp tục phiên đang mở sau khi tải lại trang, chống ghi trùng bằng idempotency và unique constraint.
- Quản lý hồ sơ, trạng thái đồng ý sinh trắc học, đăng ký từng ảnh hoặc import cả thư mục.
- Đăng ký Face ID đa góc theo năm tư thế: chính diện, trái, phải, lên và xuống.
- Engine mã nguồn mở `ageitgey/face_recognition` + dlib ResNet, lưu năm vector 128 chiều cho mỗi sinh viên.
- Nhận diện realtime bằng khoảng cách Euclidean, lấy mẫu gần nhất theo từng người và kiểm tra margin người thứ hai.
- Chấm đúng giờ/đi trễ theo chính sách từng phiên; tự đánh dấu vắng khi kết thúc.
- Lịch sử phiên, ảnh minh chứng, audit cho cập nhật thủ công và báo cáo Excel/CSV.

> Đây là bản demo học thuật chạy local. Xem `docs/DECISIONS.md` để biết các hạng mục cần nâng cấp trước production.

MVP cho he thong nhan dien khuon mat va diem danh tu dong. Thiet ke uu tien chay local tren Windows, CPU, de debug cho junior.

## Kien Truc

```mermaid
flowchart LR
    Webcam --> CameraWorker[Camera Worker]
    CameraWorker --> AIPipeline[AI Pipeline]
    AIPipeline --> API[FastAPI Backend]
    UI[Teacher/Admin UI hoac Swagger] --> API
    API --> DB[(SQLite)]
    API --> Storage[(Local Storage)]
    API --> Logs[Logs]
```

Trong MVP, chi backend duoc ghi ban ghi diem danh chinh thuc. Camera worker va AI pipeline chi gui su kien nhan dien ung vien.

## Cai Dat Tren Windows

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-camera.txt
copy .env.example .env
python scripts/init_db.py
python scripts/seed_demo.py
uvicorn backend.app.main:app --reload
```

### Cài engine Face ID trên Windows

Chạy một lần trong virtualenv. Script dùng wheel `dlib-bin` để tránh phải biên dịch dlib:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_faceid.ps1
```

Sau khi cài, vào **Khuôn mặt → Quét Face ID 5 góc**. Quy trình chỉ hoàn tất khi đã thu đủ năm góc nhìn đạt chất lượng. Import thư mục ảnh được giữ cho dữ liệu cũ/tham chiếu, không được xem là đăng ký Face ID hoàn chỉnh.

### Cài engine Face ID trên macOS Apple Silicon

Tạo `.venv` và cài hai bộ dependency như phần cài đặt ở trên, sau đó chạy:

```bash
bash scripts/install_faceid.sh
```

Script cài wheel `dlib-bin` phù hợp với Python 3.13/macOS ARM và model khuôn mặt vào `.venv`. Sau khi cài, khởi động lại backend rồi kiểm tra trang **Khuôn mặt**. `pip check` có thể báo gói `face-recognition` thiếu tên dependency `dlib`: đây là do wheel `dlib-bin` cung cấp module `dlib` dưới tên gói khác; script xác nhận engine bằng cách import và kiểm tra `supports_pose`.

Mo Swagger UI tai:

```text
http://127.0.0.1:8000/docs
```

Mo giao dien quan tri tren trinh duyet tai:

```text
http://127.0.0.1:8000/demo
```

Chay camera worker:

```powershell
pip install -r requirements-camera.txt
python camera_worker/main.py --camera 0 --api http://127.0.0.1:8000 --session-id 1 --class-id 1
```

Neu ban dang dung Python cua MSYS va pip phai build `pydantic-core` hoac OpenCV tu source, hay cai Python chinh thuc tu python.org roi tao lai `.venv`. Backend va test nghiep vu khong phu thuoc OpenCV; OpenCV chi can khi chay camera/AI.

## Test Demo Camera

### Nhận diện và tiền xử lý ảnh

Liveness/PAD và thử thách quay đầu đã được gỡ theo yêu cầu. Web/desktop gửi ảnh
trực tiếp để nhận diện; đăng ký mẫu vẫn giữ đủ năm góc. Không cần model PAD hoặc
ONNX Runtime để điểm danh. Hệ thống hiện không kiểm chứng chống ảnh in/video.

Trên máy đã có môi trường Python 3.13, chạy:

```powershell
.\.venv313\Scripts\python.exe scripts/run_web.py --reload
```

Dừng backend cũ trước khi chạy lại và tải lại trang web. Launcher local đọc lại
.env hiện tại; các khóa LIVENESS_* và WEB_LIVENESS_* cũ được bỏ qua.

PREPROCESSING_MODE=enforce bật tìm hướng/roll, căn mắt và CLAHE. Chỉ khi đổi
profile preprocessing mới cần đăng ký lại đủ năm góc cùng phiên bản; việc gỡ
liveness lần này không thay profile hoặc embedding hiện có. Xem
[hướng dẫn pipeline](docs/FACE_ANALYSIS.md), [API](docs/API.md) và
[kế hoạch nâng cấp học thuật](docs/PREPROCESSING_UPGRADE_PLAN.md).

```powershell
pip install -r requirements-camera.txt
uvicorn backend.app.main:app --reload
```

Sau do mo:

```text
http://127.0.0.1:8000/demo
```

Luot test nhanh:

1. Dang nhap tai `/demo/login` bang `admin / admin123`.
2. Mo trang **Sinh vien** de them, sua va ghi nhan trang thai dong y.
3. Mo trang **Khuon mat** de quet du 5 goc cho sinh vien da dong y. Co the nhap thu muc anh tham chieu; ten file nen bat dau bang MSSV, vi du `SV001.jpg`, `SV001_1.jpg`.
4. Mo trang **Buoi hoc**, chon lop, gio vao hoc va so phut cho phep tre, sau do mo buoi.
5. Trang **Diem danh** cho phep bat camera, quet, xem bang diem danh, dieu chinh thu cong va xuat CSV.

Giao dien gom cac URL rieng: `/demo` (tong quan), `/demo/students`, `/demo/faces`, `/demo/sessions`, `/demo/attendance`.

## Chay App Desktop

Mo terminal 1 de chay backend:

```powershell
.\.venv-win\Scripts\activate
python scripts\init_db.py
python scripts\seed_demo.py
uvicorn backend.app.main:app --reload
```

Mo terminal 2 de chay app:

```powershell
.\.venv-win\Scripts\activate
python desktop_app\main.py
```

Tai khoan demo:

```text
admin / admin123
device01 / device123
```

Luong admin:

1. Dang nhap bang `admin`.
2. Tao yeu cau diem danh gom ten lop, danh sach sinh vien, giang vien, gio vao hoc va gio ket thuc.
3. Import anh khuon mat. Ten file nen bat dau bang MSSV, vi du `SV001.jpg`, `SV001_1.jpg`.

Luong user/device:

1. Dang nhap bang `device01`.
2. Bam `Tai yeu cau` de lay cac yeu cau diem danh dang mo.
3. Chon yeu cau va bam `Bat dau diem danh`.
4. Dua mat vao camera. Khi nhan dien duoc, app hien ho ten, ma sinh vien, lop hoc va thong bao diem danh.

Hien tai desktop app da ho tro diem danh sinh vien. Diem danh giang vien nen lam o buoc tiep theo bang cach tach doi tuong nhan dien thanh `Person`/`PersonFaceTemplates` dung chung cho sinh vien va giang vien, thay vi gan tat ca vao bang `Students`.

Mac dinh demo dung header:

```text
X-User-Id: 1
X-Camera-Token: change-me-camera-token
```

## Thu Nghiem

```powershell
pytest
```

Tiền xử lý ảnh đã có profile `pre-v2`: chuẩn hóa hướng, kiểm tra chất lượng pixel
gốc, gamma/CLAHE theo vùng mặt và lọc nhiễu có điều kiện. Giữ nguyên trọng số dlib
và ngưỡng nhận diện. Profile `pre-v1` và mẫu cũ vẫn hoạt động; mặc định đo đối chiếu
v2 trên 10% lượt khi v1 đang enforce. Xem [hướng dẫn benchmark và chuyển profile](docs/PREPROCESSING_BENCHMARK.md)
và [kế hoạch/trạng thái triển khai](docs/PREPROCESSING_UPGRADE_PLAN.md).
Cài requirements-dev.txt để chạy kiểm thử HTTP và pipeline.

Nếu quay đầu hay báo không thấy mặt, có thể bật detector hỗ trợ YuNet (CPU,
không thay model nhận dạng dlib):

```powershell
python scripts/download_face_detector.py
```

Đặt `FACE_DETECTION_BACKEND=hybrid` và `PREPROCESSING_MODE=enforce` trong `.env`,
rồi khởi động lại bằng `python scripts/run_web.py --reload`. Status
`/face-analysis/status` phải có `face_detection.yunet_ready=true`. Thiếu model
thì quay về HOG và status báo lỗi; không tự tải model lúc nhận request. YuNet
chỉ hỗ trợ tìm mặt, không thay ngưỡng nhận dạng hoặc chống giả mạo. Nhánh HOG
đã nhận mặt vẫn giữ box/profile cũ nên chỉ bật detector không buộc đăng ký lại.
Nếu đổi cấu hình căn mắt/CLAHE/mirror thì vẫn cần đăng ký lại theo profile mới.

Khi điểm danh, nhiều người có thể cùng đứng trước camera. Quét tiếp tục tự động
sau khi một người được ghi nhận; khung xanh kèm tên/MSSV là đã lưu điểm danh,
khung vàng tiếp tục chờ. Chỉ bước đăng ký mẫu mới yêu cầu đúng một khuôn mặt.
Xem [hướng dẫn stream nhiều mặt](docs/STREAM_RECOGNITION.md).
Ảnh mờ/tối hoặc profile không phù hợp
vẫn bị từ chối; điểm danh thủ công tiếp tục hoạt động.

Kiểm tra lint: `python -m ruff check .` (hoặc `make lint`). Để kiểm tra giao diện
camera bằng Chrome và webcam tổng hợp, không dùng camera thật:

```powershell
python -m pip install -r requirements-browser.txt
python -m pytest -q tests/test_web_ui.py --run-browser
```

`make test` chạy unit/integration và bỏ qua Chrome khi không có --run-browser;
`make test-browser` chạy riêng nhóm giao diện. Kiểm thử tổng hợp không chứng minh
accuracy nhận diện thực tế; cần benchmark theo người/phiên/camera như kế hoạch.

## Luu Y Bao Mat

- Khong log anh khuon mat, embedding hoac token.
- Embedding van la du lieu sinh trac hoc nhay cam, khong xem la vo danh.
- Can co dong y cua sinh vien truoc khi dang ky khuon mat.
- Luon co phuong an diem danh thu cong.
