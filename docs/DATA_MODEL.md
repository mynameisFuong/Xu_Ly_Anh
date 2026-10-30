# Mô hình dữ liệu và vòng đời lưu trữ

Nguồn: [models.py](../backend/app/models.py),
[database.py](../backend/app/database.py),
[attendance.py](../backend/app/services/attendance.py). SQLAlchemy ORM dùng
SQLite mặc định; DB không đi kèm Git.

## 1. Quan hệ chính

```mermaid
erDiagram
  User ||--o{ Class : phu_trach
  User ||--o{ AuthSession : dang_nhap
  User ||--o{ DeviceClassAccess : quyen_thiet_bi
  Class ||--o{ DeviceClassAccess : cap_quyen
  Student ||--o{ ClassEnrollment : ghi_danh
  Class ||--o{ ClassEnrollment : thanh_vien
  Class ||--o{ ClassSession : mo_buoi
  Student ||--o{ FaceTemplate : mau_nhan_dien
  Student ||--o{ FaceEnrollmentDraft : mau_tam
  ClassSession ||--o{ RecognitionEvent : su_kien
  ClassSession ||--o{ AttendanceRecord : ket_qua
  Student ||--o{ AttendanceRecord : duoc_diem_danh
  RecognitionEvent o|--o{ AttendanceRecord : can_cu_tu_dong
  User o|--o{ AuditLog : thao_tac
```

Đây là quan hệ logic; SQLite mới dùng `create_all` cùng migration bổ sung một
số cột cũ. Repository chưa có Alembic hoặc cơ chế migration đầy đủ cho thay đổi
schema bất kỳ. Không coi khai báo ForeignKey là một chính sách tự động xóa file.

## 2. Các bảng

| Bảng / model | Trường chính và mục đích | Ràng buộc đáng chú ý |
| --- | --- | --- |
| users / User | username, password_hash, role, full_name, is_active | username duy nhất; vai trò admin/teacher/user. |
| auth_sessions / AuthSession | token_hash, user_id, expires_at | Hash token là khóa chính; không lưu token gốc. |
| device_class_access / DeviceClassAccess | user_id, class_id | Khóa ghép; thiết bị chỉ được cấp lớp cụ thể. |
| students / Student | student_code, full_name, class_label, consent_status, deleted_at | MSSV duy nhất kể cả hồ sơ đã xóa mềm. |
| classes / Class | code, name, teacher_id, teacher_display_name, term | code duy nhất. |
| class_enrollments / ClassEnrollment | class_id, student_id, created_at | Duy nhất (class_id, student_id); một người có thể thuộc nhiều lớp. |
| class_sessions / ClassSession | class_id, opened_by, start_time, expected_start_time, planned_end_time, late_grace_minutes, end_time, status | API chặn mở hai buổi cùng lớp; chưa có unique index có điều kiện cho trạng thái open. |
| face_templates / FaceTemplate | student_id, embedding, embedding_dim, model_name/version, pose_label, image_path, quality_score, is_active | Vector lưu bytes float32; bộ đủ năm nhãn cùng profile mới dùng nhận diện. |
| face_enrollment_drafts / FaceEnrollmentDraft | student_id, enrollment_id, owner_id, pose_label, embedding, image_bytes, model/version | Duy nhất (student_id, pose_label); có marker pose=session để quản lý lượt. |
| recognition_events / RecognitionEvent | session_id, camera_id, student_id, decision, scores, frame_time, model_version, idempotency_key | idempotency_key duy nhất. |
| attendance_records / AttendanceRecord | session_id, student_id, status, source, recognized_event_id, recorded_at, late_minutes, evidence_image_path, updated_by | Duy nhất (session_id, student_id). |
| audit_logs / AuditLog | actor, action, entity_type/id, before_json, after_json, created_at | Lưu thay đổi thủ công, seed và một số thao tác quản trị; không phải toàn bộ access log HTTP. |

Không có bảng hay model PAD/liveness. Bảng FaceTemplate lưu mẫu đối chiếu,
không phải trọng số mạng được học lại cho từng người.

## 3. Quy tắc trạng thái

`Student.consent_status`: pending → granted hoặc revoked qua thao tác quản trị.
Chỉ granted được đăng ký và tự động nhận diện. Khi chuyển khỏi granted, draft
được xóa; mẫu đã lưu còn trong DB nhưng gallery loại sinh viên do consent không
hợp lệ. Nếu được cấp lại consent, bộ mẫu còn active và đúng profile có thể dùng
lại. Xóa mềm sinh viên mới vô hiệu mẫu active; không lẫn hai thao tác này.

Đăng ký mới: tạo marker lượt → lưu tạm mỗi góc → đủ năm góc cùng profile → trong
một transaction vô hiệu bộ đang hoạt động, thêm bộ mới và xóa draft. Hủy lượt
chưa đủ không xóa bộ cũ. File ảnh và DB không có transaction phân tán; lỗi lưu
trữ có thể để lại file không được tham chiếu dù DB rollback.

`ClassSession`: open → closed. Khi đóng, tạo absent cho người ghi danh chưa có
bản ghi, giữ kết quả đã có. Không có luồng mở lại một buổi đã đóng trên web.
Người có quyền vẫn được điều chỉnh thủ công có lý do sau khi đóng.

`AttendanceRecord.status`: present, late, absent; pending trên bảng là kết quả
hiển thị khi **chưa có hàng AttendanceRecord**, không phải hàng điểm danh mới.
Nguồn auto/manual phân biệt nhận diện tự động và thao tác thủ công. Seed cũng
dùng manual; không được tính đó là model nhận diện thành công.

## 4. Thời gian và chống trùng

- API chuẩn hóa datetime UTC và trả múi giờ Z; web chuyển sang múi giờ trình duyệt.
  SQLite cũ có thể trả datetime không tz; ứng dụng hiểu là UTC.
- Hạn đúng giờ = expected_start_time + late_grace_minutes. Số phút trễ làm tròn
  lên phần giây vượt hạn. Nếu không có expected_start_time, lượt auto không tính trễ.
- Stream đã có AttendanceRecord thì trả lại hàng đó, không tạo thêm event/ảnh.
  Điều chỉnh thủ công không bị nhận diện tự động ghi đè.
- Chống lặp frame/track ở RAM hỗ trợ xác nhận; unique constraint DB mới là lớp
  ngăn hai bản ghi điểm danh cùng sinh viên/buổi.

## 5. Ảnh, vector và chuyển máy

| Nơi lưu mặc định | Nội dung | Theo Git? |
| --- | --- | --- |
| attendance.db | Metadata, hash mật khẩu/token, vector, draft, điểm danh, audit | Không. |
| storage/enrollment_images/<student> | Ảnh chân dung hiển thị 400×600 | Không. |
| storage/attendance_evidence/session-<id> | Crop JPEG mặt khi ghi nhận mới | Không. |
| storage/face-models | Trọng số detector tải riêng | Không. |
| scripts/seed_demo.py | Quy tắc sinh metadata demo | Có. |
| File export metadata JSON | Hồ sơ/lớp/ghi danh/buổi/điểm danh; không ảnh/vector | Người dùng chuyển riêng. |

Xóa sinh viên là xóa mềm và vô hiệu mẫu; **không tự xóa vật lý toàn bộ ảnh hoặc
vector lịch sử**. Thu hồi consent cũng không đồng nghĩa xóa khỏi ổ đĩa. Chưa có
CLI dọn retention hoặc mã hóa sinh trắc chuyên biệt. Hệ thống phù hợp dữ liệu
demo có kiểm soát; nếu dùng dữ liệu thật cần quy trình lưu giữ/xóa riêng.

## 6. Giới hạn ảnh hưởng việc viết báo cáo

Bảng điểm danh dựng từ **thành viên lớp hiện tại** và loại sinh viên đã xóa mềm.
Chưa có snapshot roster tại lúc mở/đóng buổi. Ghi danh thêm hoặc xóa sinh viên
sau này có thể đổi bảng/thống kê của buổi cũ; hàng AttendanceRecord cũ vẫn có
thể còn trong DB. Xuất CSV/XLSX dựa trên bảng đó, không phải sổ lịch sử bất biến.

Đổi giờ/quy định không tự tính lại bản ghi đã lưu; late_minutes của điều chỉnh
thủ công không được suy ra từ lý do. Mở một buổi/lớp được kiểm tra ở tầng dịch
vụ, chưa bảo vệ hoàn toàn đua đồng thời bằng ràng buộc schema. Track một process
không được chia sẻ giữa nhiều worker. Đây là các giới hạn cần nêu trung thực,
không phải bằng chứng hệ thống không dùng được cho bài tập lớn/demo local.
