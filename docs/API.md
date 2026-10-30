# API camera và nhận diện điểm danh

OpenAPI đầy đủ ở /docs hoặc /openapi.json. Liveness đã được gỡ; endpoint
/sessions/{id}/liveness-challenge và schema WebLivenessState không còn tồn tại.

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

/students/{id}/face-enrollment/scan vẫn hướng dẫn đủ năm góc để tạo mẫu nhận diện,
không phải thử thách trong luồng điểm danh. Upload/import dùng cùng preprocessing
và quality gate. PUT /sessions/{id}/attendance/{student_id} vẫn yêu cầu quyền,
lý do và audit. Quy tắc đúng giờ/trễ/vắng không đổi.
