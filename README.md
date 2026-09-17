# Face Attendance MVP

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
copy .env.example .env
python scripts/init_db.py
python scripts/seed_demo.py
uvicorn backend.app.main:app --reload
```

Mo Swagger UI tai:

```text
http://127.0.0.1:8000/docs
```

Mo giao dien demo camera tai:

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

```powershell
pip install -r requirements-camera.txt
uvicorn backend.app.main:app --reload
```

Sau do mo:

```text
http://127.0.0.1:8000/demo
```

Luot test nhanh:

1. Bam `Bat camera`.
2. Chon sinh vien, dua mat vao camera, bam `Dang ky anh`.
3. Chon ca hoc sang 07:00 hoac chieu 13:00.
4. Sua `Gio vao hoc` va `Cho phep tre` neu can.
5. Bam `Mo buoi`.
6. Bam `Bat dau quet`.

Bang diem danh hien ma sinh vien, ho ten, lop, thoi gian diem danh, trang thai va canh bao dung gio/tre theo cau hinh cua buoi.

Mac dinh demo dung header:

```text
X-User-Id: 1
X-Camera-Token: change-me-camera-token
```

## Thu Nghiem

```powershell
pytest
```

## Luu Y Bao Mat

- Khong log anh khuon mat, embedding hoac token.
- Embedding van la du lieu sinh trac hoc nhay cam, khong xem la vo danh.
- Can co dong y cua sinh vien truoc khi dang ky khuon mat.
- Luon co phuong an diem danh thu cong.
