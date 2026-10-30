# Kiểm chứng phần mềm và rà soát trải nghiệm

Cập nhật 31/10/2026. Tài liệu ghi phạm vi kiểm thử của phiên bản hiện hành,
không phải báo cáo thực nghiệm nhận diện trên người thật. Bản kiểm chứng PAD
ngày 29/10 đã thuộc lịch sử Git; runtime hiện không có PAD hoặc thử thách liveness.

## 1. Môi trường và cách tái lập

Máy phát triển Windows x64, môi trường Python 3.13 trong `.venv313`; trên máy
mới có thể dùng tên `.venv` theo README. Các dependency khai báo khoảng phiên
bản, chưa có lockfile tái lập toàn bộ môi trường byte-for-byte. Ghi lại
`python --version` và `python -m pip freeze` trên máy đo trước khi viết kết quả.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --run-browser
.\.venv\Scripts\python.exe -m ruff check .
node --check frontend/app.js
```

Browser test cần `requirements-browser.txt` và Google Chrome; dùng camera tổng
hợp, không truy cập webcam thật. Nếu bỏ `--run-browser`, các test browser được
skip; không ghi “toàn bộ UI đã kiểm thử” chỉ từ lệnh đó. Tests dùng DB tạm và
API/ảnh tổng hợp hoặc fixture, không tạo điểm danh vào DB demo đang chạy.

## 2. Phạm vi có bằng chứng tự động

| Nhóm | Kiểm tra chính | Căn cứ |
| --- | --- | --- |
| Hình học/ảnh | BGR/dtype, EXIF, tọa độ xoay/mirror, mask nguồn, không sửa input, nhánh gamma/CLAHE/nhiễu và fallback | test_preprocessing.py, test_face_analysis.py |
| Detector/embedding | HOG/YuNet adapter, profile, pose tương đối, từ chối ảnh chất lượng thấp | test_detection.py, test_face_recognition.py |
| Gallery/stream | Ngưỡng/margin, nhiều mẫu, frame mới, track đổi/người giao nhau, không kế thừa phiếu sai | test_gallery.py, test_streaming.py, test_temporal.py |
| Nghiệp vụ | Consent, đúng lớp/profile, đủ năm góc, bộ đăng ký tạm, rollback, chống trùng điểm danh, giờ UTC, điều chỉnh/đóng buổi | test_attendance_service.py |
| Quyền/phiên | Hash mật khẩu, token có hạn/thu hồi, phân quyền lớp, tương thích mật khẩu cũ | test_auth_sessions.py, test_password_compatibility.py |
| Dữ liệu demo/chuyển máy | Seed lặp, không ghi đè dữ liệu thật, metadata import/export không ảnh/vector | test_seed_demo.py, test_transfer_metadata.py |
| Nhập sinh viên | CSV/XLSX, xem trước, digest, dòng lỗi/trùng, giao dịch DB và UI | test_student_import.py, test_student_import_ui.py |
| Giao diện | Vòng quét nhiều mặt, overlay đúng người, màu xanh cần attendance, âm thanh, camera, lỗi trong dialog, lịch sử buổi và trạng thái rỗng | test_web_ui.py |
| Công cụ thí nghiệm | Manifest, split/chống rò dữ liệu, calibration, số liệu và dry run | test_preprocessing_benchmark.py, test_evaluate_stream.py, test_camera_worker.py |

Tên file trong bảng nằm ở [tests](../tests). Một test có tên phù hợp không tự
chứng minh mọi tình huống thực tế; xem assertions và fixture khi cần trích dẫn.

## 3. Các vấn đề UX đã sửa trong đợt rà soát

| Vấn đề quan sát từ code/luồng UI | Sửa đổi | Kiểm chứng |
| --- | --- | --- |
| Bộ năm góc thuộc profile cũ vẫn báo Hoàn tất | Summary tính theo model/profile đang chạy; hiển thị “Cần quét lại · mẫu cũ” hoặc engine chưa có | Test summary khác profile và thiếu dependency. |
| Không tắt được camera đăng ký tại chỗ | Nút Bật/Tắt, dừng draft/âm thanh, giải phóng track; thông báo khi ngắt thiết bị | Browser test kiểm tra track ended và không gửi thêm frame. |
| Đang encode nhưng không biết đang làm gì | Dòng trạng thái đang xử lý; request đăng ký có timeout 45 giây, không để chờ vô hạn | Ca đăng ký thành công/lỗi/phản hồi muộn và trạng thái sau tắt camera. |
| Lỗi quyền camera hoặc mạng khó hiểu | Hướng dẫn tiếng Việt cho bị từ chối quyền, không có/bận camera, mất backend | Browser test giả lỗi NotAllowedError. |
| Bỏ chọn/đổi buổi còn số liệu hoặc log cũ | Xóa thống kê/log/overlay, khóa thao tác cần buổi; chặn kết quả lựa chọn cũ ghi đè lựa chọn mới | Test bỏ chọn buổi, hồi quy stream. |
| Đóng buổi xong không có đường xem lại | Danh sách lịch sử gần nhất, endpoint chi tiết buổi, chế độ xem buổi đã đóng có xuất CSV/thủ công | API test buổi closed và browser test khóa camera/chính sách. |
| Lỗi lưu điều chỉnh nằm sau hộp thoại | Đưa lỗi vào dialog, giữ nội dung để sửa/thử lại | Browser test PUT thất bại. |
| Bấm lưu liên tục tạo request lặp | Khóa submit trong lúc chờ và guard submit trùng | Browser test form mở buổi với response trì hoãn. |
| Nút bấm được trước khi khởi tạo xong nên cú bấm bị bỏ qua | Nút nhập/sửa sinh viên, camera đăng ký và mở buổi bị khóa trong khi tải dữ liệu; chỉ bật sau khi gắn trình xử lý | Hồi quy UI nhập danh sách với API thật/DB tạm, đặc biệt lúc engine chưa được nạp. |
| Hồ sơ đã tạo nhưng ghi danh lớp thất bại | Giữ ID ở chế độ sửa; thông báo hồ sơ đã lưu, thử ghi danh lại thay vì tạo hồ sơ trùng | Xử lý client; cần thử lỗi mạng thực để đánh giá trải nghiệm tổng thể. |
| Bố cục mobile và buổi đã đóng chưa hợp lý | Tách nút khỏi phần mô tả; kết quả closed chiếm đủ chiều ngang, ẩn log quét và nhắc khi còn người chưa có bản ghi | Xem ảnh chụp desktop/mobile từ server local; kiểm tra không tràn ngang và không có lỗi JavaScript. |

Các bản sửa trước đó được giữ: nút ghi danh tại trang Face ID, lớp điểm danh
tách lớp hành chính, gửi frame nối tiếp, chỉ báo xanh khi đã có bản ghi, xóa
overlay cũ và log không lặp, âm thanh ngắn/dài khi quét góc.

## 4. Kết quả chạy tại máy phát triển

Lượt chạy cuối ngày 31/10/2026: `pytest -q --run-browser` đạt **216 passed**, không
skip, trong 162,56 giây trên máy phát triển. Ruff và `node --check frontend/app.js`
đạt. Hai cảnh báo thư viện: TestClient/httpx deprecation và face_recognition_models
dùng pkg_resources; không có test lỗi. Trong đó 30 ca ở test_web_ui.py và hai ca
UI nhập danh sách dùng Chrome/camera tổng hợp; các ca còn lại là unit/integration.
Ca UI nhập danh sách được chạy riêng trong process mới, engine chưa được nạp,
cũng đạt (1 passed); xác nhận lỗi bấm nút trước khởi tạo đã được sửa. Kiểm tra
Chrome trực tiếp trên server local ở 1280×900 và 390×844: không có lỗi JavaScript,
không tràn ngang toàn trang, nút mobile không chồng mô tả, buổi đóng ẩn camera
và có thể xem bảng/xuất kết quả. Kiểm tra 19 tài liệu Markdown: không có liên kết
file local hỏng hoặc code fence chưa đóng. Không bật camera vật lý ở phép kiểm tra này.
Phải chạy lại trên đúng commit/môi trường khi dùng làm minh chứng. Thời gian chạy
cả bộ test không phải độ trễ nhận diện hoặc FPS của hệ thống.

Quan sát cũ ngày 31/10: một ảnh đăng ký local xử lý jitter=1 khoảng 4,64 giây
và jitter=3 khoảng 8,90 giây. Đây là hai lượt trên **một ảnh** tại một thời
điểm, không có lặp mẫu/p95/đo công suất máy, chỉ giải thích lựa chọn mặc định
`ENROLLMENT_NUM_JITTERS=1`; không dùng để tuyên bố hệ thống nhanh gấp hai nói chung.

Các quan sát legacy/v1/v2 trên vài ảnh công khai trong tài liệu benchmark thuộc
thử nhỏ trước đây; artifact nằm local, không được phân phối cùng repo. Chưa có
bộ kết quả camera/người thật độc lập để so sánh v3 với baseline một cách tổng quát.

## 5. Việc còn phải kiểm thử thực địa

- Người thật tự đăng ký năm góc: tỷ lệ hoàn tất, thời gian, hiểu hướng quay và tiếng tít.
- Một, hai, 3–4 người vào/rời/che nhau; tên không bám sang người mới, không nhận nhầm người lạ.
- Ánh sáng khác nhau, kính, khoảng cách, camera bị ngắt và CPU yếu; đo thời gian đến ghi nhận.
- Độ đúng của bảng sau chỉnh thủ công, đóng buổi và xuất file; cho người ngoài nhóm tự thao tác.

Theo [THU_NGHIEM_DO_AN](THU_NGHIEM_DO_AN.md), ghi đúng số người/lượt, tách ảnh
đăng ký và probe khác phiên, không suy ra accuracy/FAR/FRR từ test tổng hợp.
Chưa có khả năng chống ảnh in/video; không dùng từ “liveness đạt” trong báo cáo.
Giới hạn dữ liệu lịch sử, retention, nhiều process và giao diện quản trị còn thiếu
được nêu ở [SYSTEM](SYSTEM.md), [DATA_MODEL](DATA_MODEL.md).
