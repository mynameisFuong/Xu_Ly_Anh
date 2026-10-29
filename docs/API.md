# API camera web và liveness

OpenAPI đầy đủ ở `/docs` hoặc `/openapi.json`. Giữ các endpoint nghiệp vụ hiện hành;
tài liệu này mô tả hợp đồng bổ sung cho client camera.

## Xác thực

Web/desktop dùng `X-User-Id` của tài khoản admin/teacher/user đang hoạt động theo cơ
chế demo hiện tại. Camera worker tin cậy dùng `X-Camera-Token`; không đưa token này
vào mã web/localStorage. Production phải thay xác thực demo bằng phiên đăng nhập
được xác thực, TLS và khóa camera riêng có thể thu hồi trước triển khai công khai.

## Trạng thái pipeline

`GET /face-analysis/status` (web), `GET /camera/pipeline` (camera token).
Trả engine/profile, mode, backend PAD, ready, approved, allow_pretrained,
`web_liveness_required`, `web_liveness_ready` và metrics tổng hợp.
`web_liveness_message` giải thích readiness: chưa bật enforce, thiếu engine, thiếu
model/dependency, chưa duyệt hoặc đã sẵn sàng. Thông báo không trả exception/secret.
`face_detection` trả `backend`, `yunet_ready`, lỗi tổng quát và các bộ đếm rescue
khi hybrid được cấu hình; không trả đường dẫn model. HOG vẫn dùng được nếu thiếu
model YuNet. `metrics.counts.no_face` giúp theo dõi mất mặt mà không giữ ảnh.
Bộ đếm rescue tính mỗi lần gọi detector, bao gồm canvas xoay; không dùng tỷ số
rescue/frames làm độ chính xác hoặc tỷ lệ bỏ sót.
Không có embedding, ảnh, danh tính hoặc đường dẫn model. `ready=true` chỉ chứng minh model đã nạp,
không chứng minh độ chính xác; `approved=false + allow_pretrained=true` là thử local.

## Tạo thử thách

`POST /sessions/{id}/liveness-challenge`, body `{}`, yêu cầu buổi đang mở.

```json
{
  "status": "pending",
  "challenge_id": "opaque-random-id",
  "step_token": "opaque-current-step-nonce",
  "sequence": 0,
  "action": "center",
  "step": 0,
  "total_steps": 7,
  "expires_in_seconds": 45,
  "message": "Nhìn thẳng và giữ yên khuôn mặt"
}
```

404 nếu không có buổi; 409 nếu buổi đóng; 503 nếu PAD enforce/engine chưa sẵn sàng.
Khi `WEB_LIVENESS_REQUIRED=false`, trả `status=off` cho môi trường tương thích được
quản trị viên chủ động cấu hình. Client không được tự tắt policy.

## Gửi frame

`POST /sessions/{id}/scan-frame` (web/desktop):

```json
{
  "camera_id": "browser-camera",
  "image_base64": "data:image/jpeg;base64,...",
  "idempotency_key": "new-uuid",
  "challenge_id": "id-from-server",
  "step_token": "nonce-from-latest-response",
  "sequence": 0
}
```

Giới hạn base64 2.8 triệu ký tự. Không gửi đồng thời nhiều frame; dùng sequence và
step_token server trả về, không tự tăng vượt bước. Ảnh là pixel canvas gốc, video
chỉ mirror bằng CSS. Không gửi pose/live do client tính để quyết định điểm danh.

Response có `decision`, `message`, `face_box` xywh theo pixel gốc, `liveness`:

Frame tạm mất mặt/không đạt chất lượng có thể trả `decision=unknown` cùng
`liveness.status=pending`, giữ `challenge_id` và bước, tăng sequence. Client dùng
nguyên state mới cho frame tiếp theo, không tạo thử thách mới. Frame đó không
được tính vào hold/hits và không kéo dài TTL/max-gap. Không giữ box/danh tính cũ
để vẽ thành kết quả mới. Spoof/nhiều mặt/đổi người/sai protocol vẫn trả failed.

| status | Client xử lý | Ghi điểm danh |
|---|---|---|
| required | Tạo thử thách mới | Không |
| pending | Hiển thị action/message, gửi frame mới với state vừa nhận | Không |
| failed | Hiển thị lý do, bắt đầu lại nếu người dùng tiếp tục quét | Không |
| unavailable | Dừng quét, kiểm tra model/cấu hình | Không |
| passed | Kiểm tra `decision=recognized` và `attendance` trước báo thành công | Có nếu nghiệp vụ chấp nhận |

Pending/failed không trả student_id/họ tên. Pass tiêu thụ thử thách một lần, chỉ
nhận diện cùng người trong roster đã đồng ý, đủ 5 góc cùng profile. Bản ghi trùng
trả `already_recorded=true`; không tạo thêm sự kiện/ảnh. Mỗi lần xác minh mới vẫn
cần thử thách mới. Khung hỏng trả 400; payload quá giới hạn trả 422.

## Worker và thao tác quản trị

`POST /sessions/{id}/camera-scan-frame?stream_id=...&dry_run=true` giữ hợp đồng cũ,
token camera tin cậy, PAD enforce và xác nhận nhiều frame. Worker không thực hiện
thử thách hướng dẫn người dùng trên web. `dry_run` không tạo sự kiện/bản ghi/ảnh.
`POST /sessions/{id}/recognition-events` từ chối recognized tự khai khi PAD enforce.

Các endpoint `/students/{id}/face-enrollment/scan`, upload/import kiểm tra PAD
theo cùng pipeline; chỉ tài khoản giáo viên/admin dùng được, cần consent. Đăng ký
vẫn phải được giám sát, không sử dụng kết quả import như bằng chứng hiện diện.
Thủ công qua `PUT /sessions/{id}/attendance/{student_id}` tiếp tục yêu cầu quyền,
lý do và audit. Các quy tắc đúng giờ/trễ/vắng không thay đổi.
