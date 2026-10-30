# API camera và nhận diện điểm danh

OpenAPI đầy đủ ở /docs hoặc /openapi.json. Liveness đã được gỡ; endpoint
/sessions/{id}/liveness-challenge và schema WebLivenessState không còn tồn tại.

## Nhóm endpoint nghiệp vụ

| Nhóm | Endpoint chính | Quyền |
| --- | --- | --- |
| Sức khỏe hệ thống | GET /health | Công khai, chỉ trả status. |
| Sinh viên | GET/POST /students, PATCH/DELETE /students/{id} | Admin. |
| Trạng thái Face ID | GET /admin/students/faces | Admin. |
| Lớp và ghi danh | GET/POST /classes, POST /classes/{id}/enrollments/{student_id} | GET/ghi danh: teacher/admin; tạo lớp: admin. |
| Buổi học | POST /classes/{id}/sessions, GET /attendance-requests/open, GET /sessions?limit=100 | Theo quyền lớp; lịch sử tối đa 100. |
| Chi tiết buổi | GET /sessions/{id} | User/teacher/admin theo quyền lớp, kể cả buổi đóng. |
| Chính sách/đóng buổi | PUT /sessions/{id}/policy, POST /sessions/{id}/close | Teacher/admin theo lớp; chỉ buổi mở. |
| Kết quả | GET /sessions/{id}/attendance-board, /attendance, /attendance-stats | Board: user/teacher/admin; attendance/stats: teacher/admin; luôn theo lớp. |
| Thủ công | PUT /sessions/{id}/attendance/{student_id} | Teacher/admin, reason không rỗng; cho phép sau đóng buổi. |
| Báo cáo | GET /reports/attendance.csv hoặc .xlsx?session_id={id} | Teacher/admin theo lớp. |

OpenAPI mô tả đầy đủ schema và quyền dependency trong mã. `GET /sessions/{id}`
trả `AttendanceRequestRead`: session_id, class_id/code/name, teacher_name,
expected_start_time, planned_end_time, late_grace_minutes, status, student_count.
Web dùng status=closed để khóa camera/chính sách và vẫn cho xem/xuất kết quả.
`GET /sessions` trả `SessionSummaryRead` gồm `id` (khác `session_id` ở chi tiết),
thống kê hiện tại và trạng thái; mặc định 20, giới hạn 1–100.

`GET /admin/students/faces` có `class_codes` (lớp học ghi danh), `class_label`
(lớp hành chính), số mẫu active, số góc của **profile hiện tại** và `face_status`:
`ready`, `incomplete`, `outdated`, `engine_unavailable`. `enrollment_complete`
chỉ true khi đủ năm góc của profile đang chạy; không đại diện cho quyền điểm danh
ở mọi lớp. Thiếu engine không chặn endpoint quản lý hồ sơ.

## Xác thực

Web/desktop đăng nhập bằng `POST /auth/login-json` (hoặc `/auth/login`) với JSON
`{"username":"admin","password":"..."}`. Response có `access_token`,
`token_type`, `expires_at`, `user_id`, `role`, `full_name`. Gửi
`Authorization: Bearer <access_token>` ở các request sau. `X-User-Id` không còn
được dùng để xác thực. `POST /auth/logout` thu hồi token hiện tại. Phiên mặc
định hết hạn sau tám giờ; database chỉ lưu hash của token. Mật khẩu mới dùng
PBKDF2 có salt; mật khẩu SHA-256 cũ được nâng cấp khi đăng nhập thành công.

Giảng viên chỉ truy cập phiên/lớp được giao; tài khoản thiết bị chỉ truy cập
lớp được cấp quyền. Admin cấp/thu hồi quyền bằng
`PUT` / `DELETE /classes/{class_id}/devices/{user_id}`. Các danh sách lớp,
phiên và yêu cầu đang mở được lọc theo quyền. Worker tin cậy vẫn dùng
`X-Camera-Token`; đây là quyền riêng dành cho worker backend, không đưa vào frontend.

## Nhập danh sách sinh viên

Admin tải mẫu từ `GET /students/import-template?format=csv` hoặc `format=xlsx`.
Nhập bằng `POST /students/import`, multipart/form-data:

- `file`: CSV UTF-8 (có thể BOM hoặc UTF-16 BOM, phân cách phẩy/chấm phẩy/tab)
  hoặc Excel `.xlsx`, sheet đầu tiên. Tối đa 5 MB, 2.000 sinh viên, 100 cột.
- `dry_run`: chuỗi `true` để xem trước (mặc định), `false` để nhập.
- `class_id`: không bắt buộc; chỉ ghi danh những hồ sơ mới vào lớp này.
- `expected_digest`: lấy từ response xem trước, bắt buộc khi nhập thật; gắn với
  nội dung file và lớp đã chọn. Đổi file/lớp phải xem trước lại.

Cột bắt buộc `student_code` / `MSSV` và `full_name` / `Họ và tên`.
Cột tùy chọn `class_label` / `Lớp hành chính`, `consent_status` / `Trạng thái đồng ý`.
Các cột khác được bỏ qua. Trạng thái là `pending`, `granted`, `revoked` hoặc
`Chờ đồng ý`, `Đã đồng ý`, `Đã thu hồi`; thiếu thì mặc định `pending`.
MSSV Excel nên lưu dạng Text để giữ số 0 ở đầu. Công thức trong các cột nhập
được báo lỗi, không lấy giá trị cache; định dạng số nguyên `000000` được giữ độ dài.

Response có `total`, `valid`, `imported`, `skipped`, `failed`, `digest`, `dry_run`
và `rows`. Mỗi row chứa số dòng, dữ liệu đã chuẩn hóa, `status` và `message`.
Status: `valid` (xem trước), `imported`, `duplicate`, `error`.
Các dòng lỗi và MSSV trùng được bỏ qua; không cập nhật hồ sơ/consent/Face ID hay
ghi danh cũ, không khôi phục MSSV đã xóa mềm. Xem trước không ghi DB.
Lượt nhập thật commit các dòng hợp lệ cùng ghi danh và audit trong một transaction;
xung đột ghi đồng thời trả 409 và rollback toàn lượt để xem trước lại.

## Trạng thái pipeline

GET /face-analysis/status dành cho tài khoản có quyền.
GET /camera/pipeline dành cho worker có camera token.

Response có engine, model_version, preprocessing_mode, preprocessing_version,
preprocessing_profile, shadow_candidate_profile, shadow_sample_rate, face_detection và metrics.
face_detection gồm backend, yunet_ready và metrics tổng hợp. Không trả ảnh,
embedding hoặc đường dẫn model. Khi preprocessing off, camera/pipeline không
bắt buộc backend nạp thư viện nhận diện. Không còn các trường liveness_*.
Metrics có analysis_p50_ms/analysis_p95_ms, shadow_p95_ms và các bộ đếm tổng hợp.
Shadow lấy mẫu không thay embedding hay quyết định của pipeline đang enforce.
Pipeline còn trả `stream_recognition=true`, `stream_max_faces_per_frame` và
`stream_confirmation_hits` để client chọn luồng nhiều mặt.

Giờ vào học, thời gian điểm danh và sự kiện được chuẩn hóa theo UTC; API trả
timestamp có múi giờ `Z`, giao diện hiển thị giờ địa phương của trình duyệt.
Timestamp cũ trong SQLite không có múi giờ được hiểu là UTC như nghiệp vụ hiện
có. Các buổi đã bị chỉnh sai trước khi sửa lỗi cần được người vận hành kiểm tra;
không tự thay đổi dữ liệu lịch sử.

`GET /sessions/{id}/face-readiness` trả số sinh viên được ghi danh có đủ mẫu
Face ID hợp lệ theo model hiện tại, tổng số sinh viên và trạng thái engine.
Cảnh báo trên giao diện không ngăn điểm danh thủ công.

## Stream nhiều khuôn mặt

Web/desktop dùng `POST /sessions/{id}/scan-stream` với bearer token.
Worker dùng `POST /sessions/{id}/camera-scan-stream?dry_run=false` với
`X-Camera-Token`. Hai endpoint dùng cùng body:

```json
{
  "camera_id": "browser-camera",
  "stream_id": "uuid-moi-cho-moi-lan-bat-dau",
  "frame_id": 0,
  "image_base64": "data:image/jpeg;base64,..."
}
```

`camera_id` và `stream_id` dài 1–80 ký tự. `frame_id` tăng dần từ 0, tối đa
2.147.483.647; mỗi luồng chỉ gửi một request tại một thời điểm. Giới hạn base64
là 2,8 triệu ký tự. Khi nhận response, chụp frame live mới rồi gửi tiếp;
không xếp hàng các frame cũ và không dừng sau khi điểm danh thành công.

Response có `frame_id`, `frame_width`, `frame_height`, `faces`, `message`,
`processing_ms`, `timings_ms`, `next_frame_delay_ms`. `timings_ms` tách
`inference`, `gallery`, `matching`; `processing_ms` gồm cả xác nhận và ghi DB.
Mỗi phần tử `faces` gồm:

- Các trường của kết quả một mặt: `decision`, `message`, `face_box`,
  `student_id`, `student_code`, `full_name`, `attendance`, `already_recorded`,
  `candidate_score`, `second_score`, `class_label`, `class_name`.
- `track_id`, `confirmation_hits`, `confirmation_required` để vẽ box và tiến độ.
  `face_box` là `[x,y,width,height]` theo ảnh nguồn sau áp EXIF; preview mirror
  chỉ là cách hiển thị phía client. `track_id` là mã theo dõi hình học tạm thời,
  không phải danh tính sinh viên.

Mỗi mặt được xác nhận độc lập bằng các lần so khớp mới. Mặc định cần ba lần
trong cửa sổ 30 giây; các lần tính phiếu cách nhau ít nhất 0,25 giây và bằng
chứng phải kéo dài ít nhất 0,5 giây. Gián đoạn quan sát quá 10 giây làm mất
phiếu cũ. Không phải chờ đủ 30 giây. `pending`, `unknown`,
`low_confidence`, `review` đều hiển thị vàng. Chỉ `recognized` cùng `attendance`
khác null mới được báo xanh/ghi log thành công. Tên/MSSV chưa được trả trong
giai đoạn chờ xác nhận. Khung đã mất hoặc quá hạn phải được xóa; client không
được lấy danh tính từ box cũ để gửi sự kiện điểm danh.

Backend vẫn kiểm tra lớp, đủ năm góc cùng profile, consent và phiên đang mở.
Một người chỉ có một bản ghi điểm danh trong phiên; bản ghi có sẵn trả
`already_recorded=true`, không ghi thêm sự kiện/ảnh chứng cứ. Kết quả điều chỉnh
thủ công được giữ nguyên; trạng thái cần giảng viên kiểm tra trả `review`.
`dry_run=true` xác nhận riêng, không dùng chung phiếu với luồng thật và không ghi DB.

Frame lặp/cũ hoặc trùng nội dung trong 128 frame gần nhất trả 409;
luồng đang có request xử lý hoặc hết slot trả 429. Đây không phải PAD: ảnh/video
được sửa hoặc mã hóa lại vẫn cần cơ chế chống giả mạo riêng. Client
tự thử lại với frame mới sau một khoảng nghỉ, không tăng phiếu bằng cách gửi
lại cùng `frame_id`. Base64/ảnh hỏng trả 400, payload sai/vượt giới hạn trả 422,
phiên không tồn tại trả 404, phiên đóng trả 409. Khi phiên đóng, dừng gửi frame.

Xem [hướng dẫn vận hành và giới hạn hiệu năng](STREAM_RECOGNITION.md).

Ảnh minh chứng mới được cắt theo box của người đã xác nhận và mã hóa JPEG,
thay vì lưu toàn bộ frame. Ảnh đã lưu trước đó được giữ nguyên. Engine histogram
dự phòng không được dùng để tự động ghi điểm danh qua các API scan.

## API một mặt tương thích cũ

POST /sessions/{id}/scan-frame:

```json
{
  "camera_id": "browser-camera",
  "image_base64": "data:image/jpeg;base64,...",
  "idempotency_key": "new-uuid"
}
```

Giới hạn base64 2,8 triệu ký tự, camera_id tối đa 80 ký tự. Client gửi một frame
tại một thời điểm; preview mirror bằng CSS không làm lật ảnh gửi đi.
Các trường challenge_id, step_token, sequence cũ không còn trong schema;
nếu client cũ vẫn gửi thì Pydantic bỏ qua như các trường thừa thông thường.

Response giữ decision, message, face_box (xywh theo ảnh đã giải mã/áp EXIF), student_id,
student_code, full_name, attendance và already_recorded. Không còn trường liveness.

- Ảnh nguồn không đạt chất lượng, nhiều mặt hoặc không tìm được mẫu phù hợp:
  không ghi DB và không trả danh tính.
- Chỉ dùng mẫu đủ năm góc, còn consent, được ghi danh trong lớp và cùng
  model_version với recognizer. Không ghép các profile khác nhau.
- Chỉ báo thành công khi decision=recognized và attendance khác null.
- Bản ghi trùng trả already_recorded=true, không tạo thêm sự kiện/ảnh chứng cứ.
- Base64 hỏng trả 400; vượt giới hạn payload trả 422; phiên không tồn tại trả
  404; phiên đã đóng trả 409.

## Worker

POST /sessions/{id}/camera-scan-frame?stream_id=...&dry_run=true dùng cùng body
và camera token. stream_id tối đa 80 ký tự; worker dùng một UUID cho mỗi luồng.
Backend xác nhận đủ nhiều frame theo ATTENDANCE_MIN_HITS/WINDOW_SECONDS,
reset khi frame bị từ chối hoặc đổi ứng viên. Đây là ổn định nhận diện, không
phải kiểm tra chống ảnh in/video. dry_run không ghi sự kiện, điểm danh hoặc ảnh.

POST /sessions/{id}/recognition-events vẫn dành cho worker tin cậy có token.
Không còn điều kiện PAD, nhưng quyền, consent và các quy tắc nghiệp vụ giữ nguyên.

## Đăng ký và thao tác thủ công

/students/{id}/face-enrollment/start tạo lượt quét tạm và trả `enrollment_id`.
Gửi mã này cùng mỗi request `/students/{id}/face-enrollment/scan`: năm góc mới
được lưu tạm, mẫu cũ vẫn hoạt động cho đến khi cả năm góc mới được lưu và chuyển
đổi trong cùng giao dịch DB. `DELETE /students/{id}/face-enrollment/draft` với
query `enrollment_id` hủy lượt tạm, không thay mẫu đang hoạt động. Lượt mới cho
cùng sinh viên thay lượt tạm cũ; đổi profile giữa lượt yêu cầu bắt đầu lại.
Mỗi lượt tạm thuộc người đã bắt đầu; dữ liệu tạm được xóa khi hoàn tất, hủy,
khởi tạo lượt mới, xóa sinh viên hoặc thu hồi/chuyển trạng thái đồng ý.
Nếu kết nối bị ngắt trước khi gửi hủy, lượt tạm còn trong DB đến một trong các
thao tác trên. Khởi động backend áp dụng bảng dữ liệu mới qua `create_all`.

Endpoint `/students/{id}/face-enrollment/reset` cũ vẫn vô hiệu hóa mẫu hiện có
để tương thích client cũ; giao diện mới dùng `/start` thay thế.

/students/{id}/face-enrollment/scan vẫn hướng dẫn đủ năm góc để tạo mẫu nhận diện,
không phải thử thách trong luồng điểm danh. Upload/import dùng cùng preprocessing
và quality gate. PUT /sessions/{id}/attendance/{student_id} vẫn yêu cầu quyền,
lý do và audit. Quy tắc đúng giờ/trễ/vắng không đổi.

Body scan đăng ký (thay ảnh và enrollment_id bằng giá trị thật):

```json
{
  "image_base64": "data:image/jpeg;base64,...",
  "target_pose": "left",
  "neutral_pitch": 5.0,
  "neutral_yaw": 3.0,
  "enrollment_id": "0123456789abcdef0123456789abcdef"
}
```

`target_pose`: front/left/right/up/down. Hai mốc neutral lấy từ response của
khung front đã được chấp nhận; tùy chọn để tương thích client cũ. Chúng chỉ phục
vụ hướng dẫn thu mẫu, không chứng minh liveness hoặc quyền ghi điểm danh.
Response có accepted, message, detected_pose, yaw, pitch, captured_poses,
missing_poses, progress_percent, completed, engine. Web chỉ gửi một scan đang
chờ tại một thời điểm và timeout 45 giây; hủy request HTTP không bảo đảm tác vụ
CPU phía server đã dừng, nên mã lượt/owner và transaction vẫn cần thiết.

Ảnh mẫu lấy embedding trước khi chuẩn hóa chân dung hiển thị; file chân dung
400×600 lưu local không phải vector và không nên dùng thay frame gốc để đánh
giá. Đổi profile yêu cầu đăng ký lại; giảm số jitter không đổi model/profile.
