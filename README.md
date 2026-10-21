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
pip install -r requirements-camera.txt
copy .env.example .env
python scripts/init_db.py
python scripts/seed_demo.py
uvicorn backend.app.main:app --reload
```

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
3. Mo trang **Khuon mat** de chup anh cho sinh vien da dong y, hoac nhap thu muc anh. Ten file nen bat dau bang MSSV, vi du `SV001.jpg`, `SV001_1.jpg`.
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

## Luu Y Bao Mat

- Khong log anh khuon mat, embedding hoac token.
- Embedding van la du lieu sinh trac hoc nhay cam, khong xem la vo danh.
- Can co dong y cua sinh vien truoc khi dang ky khuon mat.
- Luon co phuong an diem danh thu cong.
