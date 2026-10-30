# Điểm danh stream nhiều khuôn mặt

## Trải nghiệm

Bấm “Bắt đầu quét” một lần. Video tiếp tục chạy; A/B/C có thể cùng đứng trước
camera. Mỗi người có một khung vàng trong khi chờ, sau đó khung xanh + tên/MSSV
khi đã xác nhận và ghi nhận điểm danh. Người đã được ghi nhận có thể rời đi,
người chưa nhận diện tiếp tục đứng chờ và người mới có thể vào khung hình.
Không giữ ảnh đứng và không còn nút “Quét người tiếp theo”.

Log chỉ thêm một dòng cho mỗi bản ghi điểm danh trong buổi, không lặp hàng
trăm lần khi một người đứng lâu trước camera. Bảng thống kê cập nhật nền.
Nút dừng quét vẫn có để người vận hành chủ động kết thúc.

Mỗi người phải có đủ năm góc Face ID hợp lệ, còn đồng ý sử dụng và được ghi
danh đúng lớp. Đăng ký mẫu vẫn chỉ cho phép một mặt mỗi ảnh; âm thanh hướng
dẫn đăng ký năm góc được giữ nguyên.

Nút Làm mới cập nhật cả bảng và số Face ID hợp lệ của lớp. Bỏ chọn/đổi buổi
xóa log/thống kê tạm của buổi trước và dừng quét. Buổi đóng được xem lại từ
trang Buổi học; không gửi frame nhưng vẫn xem/xuất/điều chỉnh thủ công được.

## Kiến trúc

- [recognition.py](../ai_pipeline/recognition.py): `extract_frame_embeddings`
  giải mã và detect một lần cho frame, rồi xử lý riêng từng box. Không chọn
  người lớn nhất để bỏ qua người khác. Ảnh hỏng của một người không chặn cả nhóm.
- [analysis.py](../ai_pipeline/analysis.py): dùng cùng profile (v3 mặc định), full-frame
  coordinates và quality gate như enrollment. Không encode lại từ ảnh crop
  đã kéo giãn. Bỏ tính pose khi attendance không cần; landmark căn mắt vẫn giữ
  nếu profile yêu cầu. Shadow được lấy mẫu ở mức frame, không đổi kết quả thật.
- [streaming.py](../ai_pipeline/streaming.py): ghép box theo IoU và xác nhận
  độc lập từng track bằng các lần so khớp mới. Đổi ứng viên/không nhận diện
  được/biến mất sẽ reset riêng người đó. Không dùng danh tính cache để ghi nhận.
- [stream_recognition.py](../backend/app/services/stream_recognition.py): nạp
  gallery đúng lớp/profile, xác nhận, ghi sự kiện và điểm danh. Unique constraint
  `(session_id, student_id)` và idempotency theo người/camera/profile chống trùng.
- [app.js](../frontend/app.js): vòng request nối tiếp, luôn chụp frame mới sau
  khi xử lý xong frame trước; không tạo backlog. Video phát độc lập. Bỏ tên/khung
  cũ khi quá hạn, người rời đi hoặc kiểm tra pixel cho thấy vùng live đã thay đổi.
- [main.py](../camera_worker/main.py) và [desktop](../desktop_app/main.py): gọi
  API stream trong một worker nền, không chặn đọc/hiển thị video. Overlay nhiều
  mặt và log độc lập. Có fallback cho worker khi backend cũ chưa có API stream.

Kiểm tra pixel ở client chỉ **ẩn** màu xanh/tên khi ảnh thay đổi. Nó không
khẳng định hai ảnh là cùng một người và không được dùng để ghi điểm danh.
Danh tính và điểm danh luôn dựa vào embedding mới cùng xác nhận phía server.

## Vận hành và giới hạn thực tế

```dotenv
ATTENDANCE_MIN_HITS=3
STREAM_CONFIRMATION_WINDOW_SECONDS=30
STREAM_MAX_FACES_PER_FRAME=8
STREAM_MIN_OBSERVATION_INTERVAL_SECONDS=0.25
STREAM_MIN_CONFIRMATION_SECONDS=0.5
STREAM_MAX_OBSERVATION_GAP_SECONDS=10
```

Ba lần so khớp mới là số lần xác nhận mặc định, **không phải chờ đủ 30 giây**.
Các phiếu phải cách nhau ít nhất 0,25 giây và kéo dài ít nhất 0,5 giây.
Tracker dùng thêm dự đoán vị trí và khoảng cách embedding để ghép người;
ghép mơ hồ, đổi người hoặc gián đoạn quá 10 giây phải xây lại bằng chứng.
Ảnh trùng nội dung trong bộ nhớ 128 frame không được tính thêm phiếu dù đổi frame_id.
Các điều kiện này tăng tính nhất quán của xác nhận, không chứng minh người thật.
Cửa sổ 30 giây cho phép CPU xử lý nhiều mặt mà phiếu xác nhận không hết hạn
quá sớm. Mặc định tối đa tám mặt được encode mỗi frame; các box khác vẫn có
khung chờ và được luân phiên xử lý ở frame sau. Nếu đám đông lớn/CPU yếu, cần
đo lại tải thực, điều chỉnh ngân sách/cửa sổ hoặc dùng cấu hình phần cứng phù hợp.

Stream giữ tối đa 128 trạng thái luồng; mỗi luồng tối đa 64 track và được dọn
khi không hoạt động. Mỗi stream chỉ có một request đang xử lý; frame_id lặp
hoặc cũ bị từ chối, không tăng số phiếu xác nhận. Người/stream/camera/model khác
nhau không chia sẻ phiếu. Cùng danh tính xuất hiện ở hai box trong một frame
không được tính thành hai lần xác nhận.

So khớp dùng gallery dạng ma trận, gom các mặt trong cùng frame và chia block
để giới hạn bộ nhớ tạm. Gallery và consent vẫn đọc từ DB mỗi frame; không cache
quyền hoặc danh tính qua các lần thu hồi đồng ý. API có timings riêng cho suy luận,
đọc/chuẩn bị gallery và so khớp để xác định đúng nút thắt trước khi thêm cache.

Phiếu xác nhận nằm trong bộ nhớ tiến trình backend. Cấu hình chạy hiện tại dùng
một tiến trình; nếu triển khai nhiều worker/replica, cần định tuyến cố định cùng
stream về cùng worker hoặc chuyển trạng thái xác nhận sang kho dùng chung trước
khi mở rộng. Khởi động lại chỉ làm mất tiến độ xác nhận đang chờ; điểm danh đã
lưu vẫn nằm trong DB.

Trạng thái điều chỉnh thủ công (ví dụ vắng) không bị tự ý ghi đè. Nếu đã có
kết quả cần giảng viên kiểm tra, giao diện giữ trạng thái chờ thay vì báo xanh.
Dry-run không dùng chung phiếu với luồng thật và không ghi DB/ảnh minh chứng.

Đây là video live với suy luận từng frame mới qua HTTP. Không cam kết suy luận
30 FPS trên CPU dlib hiện tại. Smoke test ghép hai ảnh ví dụ công khai đã tìm
được hai mặt, trích xuất cả hai vector 128D; mất khoảng 3,1–3,4 giây/frame sau
khi nóng model (lượt có shadow khoảng 6,6 giây). Đăng ký cùng ảnh hai mặt vẫn
bị từ chối. Đây là kiểm tra phần mềm, chưa phải benchmark độ chính xác/công suất
với nhiều người thật và không tạo dữ liệu điểm danh vào DB local.

Luồng mới dùng nguyên profile cũ nên không buộc đăng ký lại chỉ vì bật nhiều
mặt. Nếu tự đổi pre-v1/pre-v2 hoặc tham số ảnh, quy tắc đăng ký lại vẫn áp dụng.

## Kiểm tra bằng giao diện

1. Khởi động lại backend rồi Ctrl+F5 trình duyệt để nhận API/JavaScript mới.
2. Chọn buổi đang mở và bấm bắt đầu một lần; A/B cùng vào camera.
3. Giữ A rõ mặt, B có thể thử quay/chưa rõ: A phải ghi nhận mà B vẫn vàng.
4. A rời đi, C bước vào: box A biến mất, B/C tiếp tục được nhận diện riêng.
5. Đứng lâu hoặc đi ra rồi vào lại: không tăng số dòng điểm danh/log cho cùng
   người trong buổi; thời điểm/độ trễ đã ghi trước đó không bị ghi đè.
6. Thử mất kết nối ngắn: video vẫn chạy và tự thử lại. Dừng thủ công hoặc đóng
   buổi học phải chấm dứt việc gửi frame mới.

Chi tiết schema và lỗi: [API.md](API.md).
