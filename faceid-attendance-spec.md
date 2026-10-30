> **Đặc tả gốc, không phải mô tả phiên bản hiện hành.** Tài liệu này ban đầu
> mô tả chấm công nhân viên và liveness; sản phẩm hiện là demo điểm danh sinh viên
> và đã gỡ liveness. Xem [mô tả hệ thống hiện hành](docs/SYSTEM.md). Các chỉ dẫn
> milestone, công nghệ và yêu cầu lịch sử bên dưới không tự thay đổi runtime.

# Đặc tả xây dựng hệ thống điểm danh bằng FaceID

> Tài liệu này dành cho AI agent. Hãy đọc toàn bộ trước khi viết code, làm theo thứ tự milestone ở mục 14, và chỉ chuyển milestone khi đã đạt đủ tiêu chí nghiệm thu của milestone trước.

---

## 0. Quy tắc làm việc dành cho agent

1. Không tự ý đổi công nghệ ở mục 3. Nếu thấy bắt buộc phải đổi, ghi lý do vào `docs/DECISIONS.md` rồi mới đổi.
2. Mọi cấu hình (ngưỡng, URL, khóa) lấy từ biến môi trường, không hard-code. Không commit secret; chỉ commit `.env.example`.
3. Mỗi milestone phải có test tự động chạy được bằng một lệnh (`make test`).
4. Không log ảnh, embedding hay dữ liệu sinh trắc ra stdout/log. Chỉ log ID và điểm số.
5. Khi thiếu thông tin, chọn mặc định hợp lý trong tài liệu này và ghi vào `docs/ASSUMPTIONS.md`, không dừng lại hỏi.
6. Mã nguồn và tên biến bằng tiếng Anh; comment, tài liệu và thông báo giao diện bằng tiếng Việt.
7. Sau mỗi milestone, cập nhật `README.md` với cách chạy và kiểm thử.

---

## 1. Mục tiêu và phạm vi

### 1.1 Mục tiêu
Hệ thống cho phép nhân viên chấm công vào/ra bằng cách nhìn vào camera. Hệ thống tự nhận diện, chống giả mạo, ghi nhật ký chấm công và cung cấp báo cáo cho bộ phận nhân sự.

### 1.2 Trong phạm vi (MVP)
- Đăng ký khuôn mặt nhân viên (do admin hoặc tự đăng ký có duyệt).
- Điểm danh vào/ra tại kiosk (trình duyệt có camera).
- Liveness detection (chống ảnh in, video phát lại).
- Quản trị nhân viên, phòng ban, ca làm, thiết bị.
- Báo cáo chấm công theo ngày/tháng, xuất CSV.
- Phân quyền: `admin`, `hr`, `employee`.
- Ghi nhật ký kiểm toán (audit log).

### 1.3 Ngoài phạm vi (làm sau)
- Tích hợp phần cứng chuyên dụng (máy chấm công, cửa từ).
- Nhiều chi nhánh/đa tenant.
- App mobile native (dùng web responsive).
- Tính lương.

### 1.4 Chỉ tiêu phi chức năng
| Chỉ tiêu | Mục tiêu |
|---|---|
| Thời gian từ lúc đủ khung hình đến lúc có kết quả | p95 < 1,5 giây (CPU), < 600 ms (GPU) |
| Quy mô nhân viên | Đến 5.000 người, 1 tenant |
| Số kiosk đồng thời | Đến 50 |
| Độ chính xác (kiểm thử nội bộ) | FAR ≤ 0,1%, FRR ≤ 3% ở ngưỡng mặc định |
| Khả dụng | 99,5% trong giờ làm việc |

---

## 2. Kiến trúc tổng thể

```mermaid
flowchart TB
  subgraph Clients
    K[Kiosk web - camera]
    A[Web quản trị]
    E[App nhân viên - web responsive]
  end
  GW[API Gateway - Traefik]
  subgraph Backend
    API[api-service<br/>modules: auth, enrollment, attendance, report]
    FACE[face-service<br/>detect, liveness, embed]
    WK[worker<br/>báo cáo, thông báo, dọn dữ liệu]
  end
  subgraph Data
    PG[(PostgreSQL 16 + pgvector)]
    RD[(Redis)]
    S3[(MinIO - object storage)]
  end
  K --> GW
  A --> GW
  E --> GW
  GW --> API
  API --> FACE
  API --> PG
  API --> RD
  API --> S3
  WK --> PG
  WK --> RD
  WK --> S3
```

### 2.1 Quyết định thiết kế cho MVP
- `api-service` là modular monolith gồm bốn module (auth, enrollment, attendance, report). Tách module bằng package rõ ràng để sau này tách service dễ dàng.
- `face-service` tách riêng vì tốn CPU/GPU và scale độc lập.
- Vector search dùng `pgvector` trong PostgreSQL thay vì vector DB riêng, để giảm số thành phần. Giữ interface `FaceIndex` để sau này thay bằng Qdrant/Milvus.
- Kiosk là web app (PWA) dùng `getUserMedia`, không cần cài phần mềm riêng.

---

## 3. Công nghệ

| Thành phần | Lựa chọn |
|---|---|
| Ngôn ngữ backend | Python 3.11 |
| Framework API | FastAPI + Pydantic v2 |
| ORM / migration | SQLAlchemy 2 + Alembic |
| Face detection + recognition | InsightFace (model pack `buffalo_l`: SCRFD + ArcFace, embedding 512 chiều) chạy bằng ONNX Runtime |
| Liveness | MiniFASNet (Silent-Face-Anti-Spoofing) qua ONNX Runtime |
| Database | PostgreSQL 16 + extension `pgvector` |
| Cache / hàng đợi | Redis 7 + RQ (hoặc Celery) |
| Object storage | MinIO (tương thích S3) |
| Gateway | Traefik v3 |
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind |
| Xác thực | JWT (access 15 phút, refresh 7 ngày) cho người dùng; API key (hash) cho kiosk |
| Đóng gói | Docker, Docker Compose |
| Test | pytest, httpx, Playwright (E2E) |
| Chất lượng | ruff, mypy, pre-commit |
| Quan sát | Prometheus metrics + log JSON có `request_id` |

---

## 4. Cấu trúc thư mục (monorepo)

```
faceid-attendance/
├── docker-compose.yml
├── Makefile
├── .env.example
├── README.md
├── docs/
│   ├── DECISIONS.md
│   ├── ASSUMPTIONS.md
│   └── API.md
├── services/
│   ├── api/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── core/            # config, security, logging, deps
│   │   │   ├── db/              # models, session, migrations (alembic)
│   │   │   ├── modules/
│   │   │   │   ├── auth/
│   │   │   │   ├── employees/
│   │   │   │   ├── enrollment/
│   │   │   │   ├── attendance/
│   │   │   │   ├── devices/
│   │   │   │   └── reports/
│   │   │   ├── face_client.py   # gọi face-service
│   │   │   └── face_index.py    # interface FaceIndex + PgVectorIndex
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── face/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── detector.py
│   │   │   ├── liveness.py
│   │   │   ├── embedder.py
│   │   │   └── quality.py
│   │   ├── models/              # tải model khi build, không commit file nặng
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── worker/
│       ├── worker/
│       └── tests/
├── web/
│   ├── admin/                   # Next.js: quản trị + app nhân viên
│   └── kiosk/                   # Next.js: giao diện kiosk
└── deploy/
    ├── traefik/
    └── k8s/                     # (tùy chọn, giai đoạn sau)
```

---

## 5. Face service

Dịch vụ nội bộ, không public ra internet. Chỉ `api-service` được gọi.

### 5.1 Endpoint

| Method | Path | Mô tả |
|---|---|---|
| POST | `/v1/analyze` | Nhận 1 ảnh, trả về detect + chất lượng + liveness + embedding |
| POST | `/v1/embed` | Nhận 1 ảnh đã căn chỉnh, trả về embedding (dùng cho enrollment nhiều ảnh) |
| GET | `/healthz` | Kiểm tra sống |
| GET | `/readyz` | Kiểm tra model đã nạp |

### 5.2 `POST /v1/analyze`

Request: `multipart/form-data` với trường `image` (JPEG/PNG, tối đa 2 MB) và `mode` = `checkin` hoặc `enroll`.

Response 200:
```json
{
  "face_found": true,
  "face_count": 1,
  "bbox": [x1, y1, x2, y2],
  "quality": {
    "face_size_px": 142,
    "blur_score": 0.91,
    "pose_yaw_deg": 8.2,
    "pose_pitch_deg": -4.1,
    "brightness": 0.58,
    "passed": true,
    "reasons": []
  },
  "liveness": { "score": 0.97, "passed": true },
  "embedding": [0.0123, "... 512 số float32, đã chuẩn hóa L2 ..."]
}
```

Quy tắc:
- Nếu có nhiều khuôn mặt, chọn mặt lớn nhất và đặt `face_count` đúng số mặt; API quyết định có chấp nhận hay không (mặc định: từ chối khi `face_count > 1`).
- Nếu `mode=enroll`, `quality.passed=false` khi không đạt ngưỡng chất lượng ở 5.3. Với `mode=checkin`, dùng ngưỡng nới hơn.
- Chỉ trả `embedding` khi `quality.passed` và `liveness.passed` đều đúng.
- Embedding luôn được chuẩn hóa L2 để cosine similarity = tích vô hướng.

### 5.3 Ngưỡng chất lượng mặc định (đều cấu hình qua env)

| Tham số | Enroll | Check-in |
|---|---|---|
| `MIN_FACE_SIZE_PX` | 112 | 80 |
| `MAX_YAW_DEG` | 20 | 30 |
| `MAX_PITCH_DEG` | 20 | 25 |
| `MIN_BLUR_SCORE` | 0,6 | 0,45 |
| `MIN_BRIGHTNESS` / `MAX_BRIGHTNESS` | 0,25 / 0,85 | 0,2 / 0,9 |
| `LIVENESS_THRESHOLD` | 0,85 | 0,80 |

### 5.4 Hiệu năng
- Nạp model một lần khi khởi động, dùng ONNX Runtime session tái sử dụng.
- Hỗ trợ `ONNX_PROVIDER=cpu|cuda` qua env.
- Giới hạn đồng thời bằng semaphore (`FACE_MAX_CONCURRENCY`, mặc định 4).

---

## 6. Mô hình dữ liệu

### 6.1 Sơ đồ quan hệ

```mermaid
erDiagram
  DEPARTMENTS ||--o{ EMPLOYEES : has
  SHIFTS ||--o{ EMPLOYEES : assigned_to
  EMPLOYEES ||--o{ FACE_TEMPLATES : owns
  EMPLOYEES ||--o{ ATTENDANCE_LOGS : records
  DEVICES ||--o{ ATTENDANCE_LOGS : captures
  EMPLOYEES ||--o| USERS : login
  USERS ||--o{ AUDIT_LOGS : performs
```

### 6.2 DDL tham chiếu (PostgreSQL)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE departments (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shifts (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name           text NOT NULL,
  start_time     time NOT NULL,
  end_time       time NOT NULL,
  grace_minutes  int  NOT NULL DEFAULT 10,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE employees (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code           text NOT NULL UNIQUE,
  full_name      text NOT NULL,
  email          text UNIQUE,
  department_id  uuid REFERENCES departments(id),
  shift_id       uuid REFERENCES shifts(id),
  status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  consent_at     timestamptz,            -- thời điểm đồng ý dùng dữ liệu sinh trắc
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_id    uuid REFERENCES employees(id),
  username       text NOT NULL UNIQUE,
  password_hash  text NOT NULL,           -- argon2id
  role           text NOT NULL CHECK (role IN ('admin','hr','employee')),
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE face_templates (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_id    uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  embedding      vector(512) NOT NULL,
  model_version  text NOT NULL,           -- ví dụ 'buffalo_l@1'
  quality_score  real,
  is_active      boolean NOT NULL DEFAULT true,
  enrolled_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX face_templates_hnsw
  ON face_templates USING hnsw (embedding vector_cosine_ops);
CREATE INDEX face_templates_employee ON face_templates(employee_id);

CREATE TABLE devices (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  location      text,
  api_key_hash  text NOT NULL,            -- sha256 của khóa, không lưu khóa thô
  is_active     boolean NOT NULL DEFAULT true,
  last_seen_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE attendance_logs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_id     uuid NOT NULL REFERENCES employees(id),
  device_id       uuid NOT NULL REFERENCES devices(id),
  type            text NOT NULL CHECK (type IN ('in','out')),
  similarity      real NOT NULL,
  liveness_score  real NOT NULL,
  evidence_key    text,                   -- khóa object trong MinIO
  checked_at      timestamptz NOT NULL DEFAULT now(),
  source          text NOT NULL DEFAULT 'face' CHECK (source IN ('face','manual'))
);
CREATE INDEX attendance_emp_time ON attendance_logs(employee_id, checked_at DESC);

CREATE TABLE audit_logs (
  id          bigserial PRIMARY KEY,
  user_id     uuid REFERENCES users(id),
  action      text NOT NULL,
  target_type text,
  target_id   text,
  detail      jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

### 6.3 Ghi chú bảo mật dữ liệu sinh trắc
`pgvector` cần vector ở dạng thô để tìm kiếm, nên không mã hóa ở mức cột được. Biện pháp bù: mã hóa ổ đĩa/volume của PostgreSQL, bật TLS giữa api và DB, dùng role DB riêng với quyền tối thiểu cho `face_templates`, và không bao giờ trả embedding qua API công khai. Ghi quyết định này vào `docs/DECISIONS.md`.

---

## 7. Đặc tả API (`api-service`)

Tiền tố `/api/v1`. Lỗi trả theo dạng:
```json
{ "error": { "code": "NO_FACE", "message": "Không phát hiện khuôn mặt" } }
```

### 7.1 Xác thực
| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| POST | `/auth/login` | public | `{username,password}` → `{access_token, refresh_token}` |
| POST | `/auth/refresh` | public | Đổi refresh token lấy access token mới |
| POST | `/auth/logout` | user | Vô hiệu refresh token (lưu denylist trong Redis) |

Giới hạn đăng nhập sai: 5 lần/15 phút/IP+username, sau đó khóa tạm.

### 7.2 Quản lý danh mục
| Method | Path | Quyền |
|---|---|---|
| GET/POST | `/departments`, `/shifts` | admin, hr |
| GET/PATCH/DELETE | `/departments/{id}`, `/shifts/{id}` | admin, hr |
| GET/POST | `/employees` (có phân trang, lọc theo phòng ban, trạng thái, từ khóa) | admin, hr |
| GET/PATCH | `/employees/{id}` | admin, hr; employee chỉ xem chính mình |
| POST | `/employees/{id}/deactivate` | admin, hr (đồng thời vô hiệu hóa face_templates) |
| GET/POST | `/devices` | admin |
| POST | `/devices/{id}/rotate-key` | admin (trả khóa mới đúng một lần) |

### 7.3 Đăng ký khuôn mặt

`POST /employees/{id}/enrollment` (admin, hr, hoặc chính employee nếu được bật)
- Body: `multipart/form-data`, trường `images` gồm 3 đến 5 ảnh, kèm `consent=true`.
- Quy trình: với mỗi ảnh gọi `face-service /v1/analyze?mode=enroll`; loại ảnh không đạt chất lượng; cần tối thiểu 3 ảnh đạt. Kiểm tra trùng: nếu embedding khớp một nhân viên khác với cosine ≥ `DUPLICATE_FACE_THRESHOLD` (mặc định 0,6) thì từ chối `FACE_ALREADY_ENROLLED`. Lưu các template, ghi `consent_at`, ghi audit log.
- Response 201: `{ "employee_id": "...", "templates_saved": 4, "rejected": [{"index":2,"reasons":["blur"]}] }`

`DELETE /employees/{id}/enrollment` (admin, hr, hoặc chính chủ): xóa toàn bộ template của nhân viên và ghi audit log.

### 7.4 Điểm danh (kiosk)

`POST /attendance/checkin`
- Xác thực: header `X-Device-Key: <khóa>`.
- Body: `multipart/form-data`, trường `image` (một khung hình).
- Quy trình:
  1. Gọi `face-service /v1/analyze?mode=checkin`.
  2. Nếu không có mặt, nhiều mặt, chất lượng kém hoặc liveness fail → trả lỗi tương ứng (7.4.1).
  3. Tìm top-5 gần nhất trong `face_templates` (chỉ `is_active` và nhân viên `active`) bằng cosine.
  4. Lấy điểm cao nhất theo từng nhân viên. Nếu điểm ≥ `MATCH_THRESHOLD` (mặc định 0,45) và chênh lệch với người thứ hai ≥ `MATCH_MARGIN` (mặc định 0,05) thì coi là khớp.
  5. Áp dụng quy tắc chấm công (mục 9). Lưu ảnh bằng chứng lên MinIO (nếu bật `STORE_EVIDENCE`).
  6. Ghi `attendance_logs`, đẩy sự kiện thông báo vào hàng đợi.
- Response 200:
```json
{
  "status": "matched",
  "employee": { "id": "...", "code": "NV001", "full_name": "Nguyễn Văn A" },
  "type": "in",
  "checked_at": "2026-10-21T08:02:11+07:00",
  "similarity": 0.71
}
```

#### 7.4.1 Mã lỗi điểm danh
| Code | HTTP | Ý nghĩa |
|---|---|---|
| `NO_FACE` | 422 | Không thấy khuôn mặt |
| `MULTIPLE_FACES` | 422 | Có nhiều hơn một khuôn mặt |
| `LOW_QUALITY` | 422 | Mặt quá nhỏ, mờ, lệch, thiếu sáng (kèm `reasons`) |
| `SPOOF_SUSPECTED` | 403 | Liveness không đạt |
| `NOT_RECOGNIZED` | 404 | Không khớp ai |
| `TOO_SOON` | 409 | Vừa chấm công trong khoảng debounce |
| `DEVICE_INVALID` | 401 | Khóa thiết bị sai hoặc bị vô hiệu |

`POST /attendance/manual` (admin, hr): thêm bản ghi thủ công `{employee_id, type, checked_at, reason}`, `source='manual'`, bắt buộc có `reason`, ghi audit log.

### 7.5 Báo cáo
| Method | Path | Mô tả |
|---|---|---|
| GET | `/attendance/logs` | Lọc theo nhân viên, phòng ban, khoảng ngày; phân trang |
| GET | `/reports/daily?date=YYYY-MM-DD` | Mỗi nhân viên: giờ vào đầu, giờ ra cuối, đi muộn, về sớm, vắng |
| GET | `/reports/monthly?month=YYYY-MM` | Tổng hợp theo tháng |
| GET | `/reports/export?type=daily\|monthly&...&format=csv` | Xuất CSV (UTF-8 có BOM để Excel đọc tiếng Việt) |
| GET | `/me/attendance` | Employee xem lịch sử của chính mình |

### 7.6 Khác
`GET /healthz`, `GET /readyz`, `GET /metrics` (Prometheus, chỉ mạng nội bộ).

---

## 8. Giao diện

### 8.1 Kiosk (`web/kiosk`)
- Mở camera trước, hiển thị khung xem trước và vòng hướng dẫn đặt mặt.
- Chạy phát hiện mặt nhẹ phía trình duyệt (ví dụ MediaPipe Face Detection) để chỉ gửi khung hình khi có đúng một mặt đủ lớn, ổn định khoảng 300 ms. Tối đa 3 khung hình/giây.
- Sau khi gửi, hiển thị kết quả toàn màn hình: xanh + tên + "Vào/Ra" + giờ khi thành công; đỏ + lý do tiếng Việt khi lỗi. Tự quay về trạng thái chờ sau 3 giây.
- Lưu API key thiết bị trong `localStorage` sau bước kích hoạt thiết bị bằng mã một lần do admin tạo.
- Có chế độ nhập mã nhân viên + PIN dự phòng khi nhận diện lỗi (tùy chọn, bật bằng cấu hình).
- Âm thanh/phản hồi: tiếng "bíp" khác nhau cho thành công/thất bại.

### 8.2 Web quản trị (`web/admin`)
- Đăng nhập, phân quyền theo vai trò.
- Trang: Tổng quan (số người đã vào hôm nay, đi muộn, vắng); Nhân viên (CRUD, trạng thái đăng ký mặt); Đăng ký khuôn mặt (chụp từ webcam, hiển thị chất lượng từng ảnh); Phòng ban; Ca làm; Thiết bị (tạo, xoay khóa, xem `last_seen_at`); Nhật ký chấm công (bộ lọc, xem ảnh bằng chứng); Báo cáo (ngày/tháng, xuất CSV); Nhật ký kiểm toán.
- Tất cả văn bản giao diện bằng tiếng Việt, định dạng ngày `dd/MM/yyyy`, múi giờ `Asia/Ho_Chi_Minh`.

### 8.3 App nhân viên
- Cùng codebase `web/admin`, route `/me`: xem lịch sử chấm công, xem trạng thái đăng ký mặt, yêu cầu xóa dữ liệu khuôn mặt.

---

## 9. Quy tắc nghiệp vụ chấm công

- Múi giờ hệ thống: `Asia/Ho_Chi_Minh`; lưu DB bằng `timestamptz` (UTC).
- Debounce: không ghi thêm bản ghi cho cùng nhân viên trong `DEBOUNCE_SECONDS` (mặc định 60); trả `TOO_SOON`.
- Xác định `in`/`out`: sự kiện đầu tiên trong ngày là `in`; các sự kiện sau luân phiên `out`, `in`, `out`... Ngày làm việc tính theo `WORKDAY_CUTOFF_HOUR` (mặc định 04:00) để hỗ trợ ca đêm.
- Đi muộn: giờ `in` đầu tiên > `shift.start_time + grace_minutes`.
- Về sớm: giờ `out` cuối cùng < `shift.end_time`.
- Vắng: nhân viên `active` có ca nhưng không có bản ghi `in` trong ngày làm việc đã đóng.
- Báo cáo ngày được tính lại bởi worker lúc 00:30 hằng ngày và có thể tính theo yêu cầu.
- Nhân viên `inactive` không thể được nhận diện.

---

## 10. Bảo mật và quyền riêng tư

- HTTPS bắt buộc; Traefik cấp chứng chỉ (Let's Encrypt hoặc chứng chỉ nội bộ).
- Mật khẩu băm argon2id. JWT ký HS256 với `JWT_SECRET` dài tối thiểu 32 byte.
- Kiosk dùng API key ngẫu nhiên 32 byte, lưu hash SHA-256, có thể thu hồi/xoay.
- Rate limit ở gateway: `/auth/login` 10 req/phút/IP; `/attendance/checkin` 30 req/phút/thiết bị.
- Face service chỉ nằm trong mạng Docker nội bộ, không publish cổng ra ngoài.
- Không lưu ảnh gốc khi đăng ký; chỉ lưu embedding. Ảnh bằng chứng điểm danh là tùy chọn, mã hóa phía server (SSE) và tự xóa sau `EVIDENCE_RETENTION_DAYS` (mặc định 30).
- Bắt buộc có đồng ý của nhân viên (`consent_at`) trước khi lưu embedding.
- Khi nhân viên nghỉ việc hoặc yêu cầu xóa: xóa `face_templates` và ảnh bằng chứng liên quan trong vòng 7 ngày; ghi audit log.
- Audit log cho mọi thao tác nhạy cảm: đăng ký/xóa khuôn mặt, tạo/xoay khóa thiết bị, chấm công thủ công, thay đổi quyền, xuất báo cáo.
- Tuân thủ tinh thần Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân: mục đích rõ ràng, tối thiểu hóa dữ liệu, có thông báo và đồng ý, có thời hạn lưu trữ. Soạn mẫu văn bản đồng ý trong `docs/CONSENT_TEMPLATE.md`.

---

## 11. Cấu hình môi trường (`.env.example`)

```env
# Chung
TZ=Asia/Ho_Chi_Minh
APP_ENV=dev

# Database
POSTGRES_USER=faceid
POSTGRES_PASSWORD=change_me
POSTGRES_DB=faceid
DATABASE_URL=postgresql+psycopg://faceid:change_me@postgres:5432/faceid

# Redis
REDIS_URL=redis://redis:6379/0

# MinIO
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=change_me
S3_SECRET_KEY=change_me
S3_BUCKET=faceid-evidence
STORE_EVIDENCE=true
EVIDENCE_RETENTION_DAYS=30

# Auth
JWT_SECRET=change_me_at_least_32_bytes_long_random
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=7

# Face service
FACE_SERVICE_URL=http://face:8001
ONNX_PROVIDER=cpu
FACE_MAX_CONCURRENCY=4
LIVENESS_THRESHOLD_CHECKIN=0.80
LIVENESS_THRESHOLD_ENROLL=0.85

# Nhận diện
MATCH_THRESHOLD=0.45
MATCH_MARGIN=0.05
DUPLICATE_FACE_THRESHOLD=0.60
DEBOUNCE_SECONDS=60
WORKDAY_CUTOFF_HOUR=4
```

---

## 12. Triển khai

`docker-compose.yml` gồm các service: `traefik`, `api`, `face`, `worker`, `web-admin`, `web-kiosk`, `postgres` (image có sẵn pgvector, ví dụ `pgvector/pgvector:pg16`), `redis`, `minio`.

Yêu cầu:
- Healthcheck cho mọi service; `api` chờ `postgres` và `face` sẵn sàng.
- Volume bền vững cho `postgres` và `minio`.
- `make up` khởi động toàn bộ, `make migrate` chạy Alembic, `make seed` tạo admin đầu tiên và dữ liệu mẫu, `make test` chạy toàn bộ test, `make lint` chạy ruff + mypy.
- Model ONNX tải trong bước build Docker của `face` (có script `scripts/download_models.sh`), không commit vào git.
- Lệnh `make seed` đọc `ADMIN_USERNAME` và `ADMIN_PASSWORD` từ env, không có mật khẩu mặc định cố định trong mã.

---

## 13. Chiến lược kiểm thử

### 13.1 Unit và integration
- `api`: test từng module với DB PostgreSQL thật (testcontainers hoặc service trong CI), mock `face-service` bằng embedding giả lập.
- `face`: test với bộ ảnh mẫu trong `services/face/tests/fixtures` (ảnh tổng hợp hoặc ảnh có giấy phép, không dùng ảnh người thật chưa xin phép).
- Test quy tắc chấm công (mục 9) bằng bảng ca: ca ngày, ca đêm qua nửa đêm, đi muộn trong/ngoài grace, debounce, nhân viên inactive.

### 13.2 End-to-end
- Playwright: đăng nhập admin → tạo nhân viên → đăng ký mặt (dùng video giả lập qua `--use-fake-device-for-media-stream`) → kiosk điểm danh → xem trong nhật ký → xuất CSV.

### 13.3 Đánh giá chất lượng nhận diện
- Viết script `scripts/eval_recognition.py` nhận thư mục `dataset/<employee_code>/*.jpg`, đăng ký một phần ảnh và kiểm thử phần còn lại, in ra FAR, FRR, đường ROC và ngưỡng đề xuất. Dùng để chỉnh `MATCH_THRESHOLD` theo dữ liệu thật của đơn vị.

### 13.4 Hiệu năng
- Locust hoặc k6: 50 kiosk mô phỏng, 1 yêu cầu/3 giây/kiosk, kiểm tra p95 theo mục 1.4.

---

## 14. Kế hoạch triển khai theo milestone

### M0. Khung dự án
- Việc cần làm: tạo monorepo, `docker-compose.yml`, Makefile, CI (lint + test), `.env.example`, Traefik, PostgreSQL + pgvector, Redis, MinIO.
- Nghiệm thu: `make up` chạy được; `GET /healthz` của api và face trả 200; CI xanh.

### M1. Dữ liệu và xác thực
- Việc cần làm: migration cho toàn bộ bảng mục 6.2; module auth (login, refresh, logout, rate limit); CRUD departments, shifts, employees, devices; phân quyền theo vai trò; audit log.
- Nghiệm thu: test phân quyền pass (employee không truy cập được API admin); tạo thiết bị trả khóa đúng một lần; `make seed` tạo được admin.

### M2. Face service
- Việc cần làm: `/v1/analyze`, `/v1/embed`; detector, quality, liveness, embedder; ngưỡng qua env; semaphore đồng thời.
- Nghiệm thu: với ảnh mẫu, trả đúng 512 chiều đã chuẩn hóa L2; ảnh mờ/nhỏ/lệch bị loại với `reasons` đúng; ảnh in/ảnh chụp màn hình bị liveness từ chối trong bộ test nội bộ; p95 đạt mục tiêu CPU.

### M3. Đăng ký khuôn mặt
- Việc cần làm: `POST/DELETE /employees/{id}/enrollment`, kiểm tra `consent`, kiểm tra trùng, lưu `face_templates` với index HNSW, giao diện chụp ảnh trong web quản trị.
- Nghiệm thu: đăng ký 3 đến 5 ảnh thành công; ảnh kém bị báo lý do; đăng ký trùng mặt người khác bị chặn; xóa đăng ký xóa sạch template.

### M4. Điểm danh
- Việc cần làm: `POST /attendance/checkin` đầy đủ luồng mục 7.4; `FaceIndex`/`PgVectorIndex`; quy tắc mục 9; lưu bằng chứng; chấm công thủ công; giao diện kiosk.
- Nghiệm thu: nhận diện đúng người trong bộ test; người lạ nhận `NOT_RECOGNIZED`; debounce hoạt động; ca đêm tính đúng ngày làm việc; E2E kiosk pass; p95 trong mục tiêu.

### M5. Báo cáo và thông báo
- Việc cần làm: nhật ký có lọc, báo cáo ngày/tháng, xuất CSV UTF-8 BOM, job tính lại báo cáo, thông báo email khi đi muộn/vắng (SMTP cấu hình qua env), trang `/me`.
- Nghiệm thu: số liệu báo cáo khớp dữ liệu test; CSV mở đúng tiếng Việt trong Excel; employee chỉ thấy dữ liệu của mình.

### M6. Bảo mật và vận hành
- Việc cần làm: rate limit, TLS, chính sách lưu trữ và job xóa ảnh bằng chứng, endpoint xóa dữ liệu theo yêu cầu, Prometheus metrics, log JSON có `request_id`, tài liệu `docs/CONSENT_TEMPLATE.md`.
- Nghiệm thu: quét phụ thuộc không có lỗ hổng mức cao; không có secret trong git; job retention xóa đúng dữ liệu quá hạn; metrics có độ trễ và tỉ lệ lỗi theo endpoint.

### M7. Đánh giá và bàn giao
- Việc cần làm: chạy `scripts/eval_recognition.py` và load test, đề xuất ngưỡng, hoàn thiện `README.md`, `docs/API.md` (xuất từ OpenAPI), hướng dẫn vận hành và sao lưu.
- Nghiệm thu: báo cáo đánh giá FAR/FRR/độ trễ trong `docs/EVALUATION.md`; một người mới chạy được toàn hệ thống chỉ bằng README.

---

## 15. Định nghĩa hoàn thành (Definition of Done)

Một milestone chỉ hoàn thành khi:
1. Tất cả tiêu chí nghiệm thu của milestone đạt.
2. `make lint` và `make test` đều xanh.
3. Không có TODO hoặc code giả (stub) còn sót trong luồng chính.
4. `README.md` và `docs/API.md` phản ánh đúng thay đổi.
5. Không có dữ liệu sinh trắc, secret hay ảnh người thật bị commit vào repo.

---

## 16. Rủi ro đã biết và cách xử lý

| Rủi ro | Cách giảm thiểu |
|---|---|
| Giả mạo bằng ảnh/video | Liveness + ngưỡng chặt khi enroll; cân nhắc camera IR ở giai đoạn sau |
| Nhận nhầm người (FAR) | Dùng `MATCH_MARGIN`, hiệu chỉnh ngưỡng bằng dữ liệu thật, lưu ảnh bằng chứng để đối soát |
| Từ chối nhầm nhân viên thật (FRR) | Đăng ký 3 đến 5 ảnh đa dạng góc/sáng; nút nhập mã dự phòng; cho phép đăng ký bổ sung |
| Thiếu sáng, ngược sáng | Kiểm tra độ sáng, hiển thị hướng dẫn trên kiosk |
| Rò rỉ dữ liệu sinh trắc | Hạn chế quyền DB, mã hóa ổ đĩa, TLS, audit log, chính sách xóa |
| Thay đổi model làm embedding không tương thích | Lưu `model_version`; khi nâng cấp phải đăng ký lại hoặc chạy migration song song |
| Quá tải CPU | Giới hạn đồng thời, hỗ trợ GPU qua `ONNX_PROVIDER=cuda`, scale ngang `face-service` |
