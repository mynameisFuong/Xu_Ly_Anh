import base64
import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    Button,
    Entry,
    Frame,
    Label,
    Listbox,
    StringVar,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
    ttk,
)

import cv2
import requests


API_BASE = "http://127.0.0.1:8000"


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_id: int | None = None
        self.role: str | None = None
        self.full_name: str | None = None

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.ok:
            return
        detail = response.text
        try:
            body = response.json()
            detail = body.get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"{response.status_code}: {detail}")

    def login(self, username: str, password: str) -> dict:
        response = requests.post(
            f"{self.base_url}/auth/login",
            params={"username": username, "password": password},
            timeout=10,
        )
        self._raise_for_status(response)
        data = response.json()
        self.user_id = int(data["user_id"])
        self.role = str(data["role"])
        self.full_name = str(data["full_name"])
        return data

    def headers(self) -> dict[str, str]:
        if self.user_id is None:
            raise RuntimeError("Not logged in")
        return {"X-User-Id": str(self.user_id)}

    def get(self, path: str) -> dict | list:
        response = requests.get(f"{self.base_url}{path}", headers=self.headers(), timeout=10)
        self._raise_for_status(response)
        return response.json()

    def post_json(self, path: str, payload: dict) -> dict:
        response = requests.post(
            f"{self.base_url}{path}",
            headers={**self.headers(), "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=20,
        )
        self._raise_for_status(response)
        return response.json()

    def post_files(self, path: str, file_paths: list[Path]) -> dict:
        files = [("files", (item.name, item.open("rb"), "image/jpeg")) for item in file_paths]
        try:
            response = requests.post(f"{self.base_url}{path}", headers=self.headers(), files=files, timeout=120)
            self._raise_for_status(response)
            return response.json()
        finally:
            for _name, file_tuple in files:
                file_tuple[1].close()

    def download_bytes(self, path: str) -> bytes:
        response = requests.get(f"{self.base_url}{path}", headers=self.headers(), timeout=20)
        self._raise_for_status(response)
        return response.content


class App:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Face Attendance App")
        self.root.geometry("980x640")
        self.api = ApiClient(API_BASE)
        self.camera_running = False
        self.capture: cv2.VideoCapture | None = None
        self.active_session_id: int | None = None
        self._build_login()

    def _clear(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

    def _build_login(self) -> None:
        self._clear()
        frame = Frame(self.root, padx=24, pady=24)
        frame.pack(fill=BOTH, expand=True)
        Label(frame, text="Face Attendance App", font=("Arial", 22, "bold")).pack(anchor="w", pady=(0, 20))

        username = StringVar(value="admin")
        password = StringVar(value="admin123")
        api_base = StringVar(value=API_BASE)

        Label(frame, text="Backend URL").pack(anchor="w")
        Entry(frame, textvariable=api_base, width=44).pack(anchor="w", pady=(0, 10))
        Label(frame, text="Username").pack(anchor="w")
        Entry(frame, textvariable=username, width=32).pack(anchor="w", pady=(0, 10))
        Label(frame, text="Password").pack(anchor="w")
        Entry(frame, textvariable=password, width=32, show="*").pack(anchor="w", pady=(0, 14))

        def do_login() -> None:
            try:
                self.api = ApiClient(api_base.get())
                self.api.login(username.get(), password.get())
            except Exception as exc:
                messagebox.showerror("Login failed", str(exc))
                return
            if self.api.role == "admin":
                self._build_admin()
            else:
                self._build_user()

        Button(frame, text="Dang nhap", command=do_login, width=18).pack(anchor="w")
        Label(
            frame,
            text="Demo: admin/admin123 hoac device01/device123",
            fg="#667085",
        ).pack(anchor="w", pady=(14, 0))

    def _build_admin(self) -> None:
        self._clear()
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=BOTH, expand=True, padx=12, pady=12)

        request_tab = Frame(notebook, padx=14, pady=14)
        import_tab = Frame(notebook, padx=14, pady=14)
        students_tab = Frame(notebook, padx=14, pady=14)
        notebook.add(request_tab, text="Tao yeu cau diem danh")
        notebook.add(import_tab, text="Import khuon mat")
        notebook.add(students_tab, text="Sinh vien")

        class_code = StringVar(value="IMG101")
        class_name = StringVar(value="Xu Ly Anh")
        teacher_name = StringVar(value="Demo Teacher")
        start_time = StringVar(value=self._default_time(7))
        end_time = StringVar(value=self._default_time(10))
        grace = StringVar(value="0")

        fields = [
            ("Ma lop", class_code),
            ("Ten lop hoc", class_name),
            ("Giang vien", teacher_name),
            ("Thoi gian vao hoc ISO", start_time),
            ("Thoi gian ket thuc ISO", end_time),
            ("Cho phep tre phut", grace),
        ]
        for label, var in fields:
            Label(request_tab, text=label).pack(anchor="w")
            Entry(request_tab, textvariable=var, width=58).pack(anchor="w", pady=(0, 8))

        Label(request_tab, text="Danh sach sinh vien: moi dong MSSV,Ho ten,Lop").pack(anchor="w")
        students_box = Listbox(request_tab, height=9, width=80)
        students_box.pack(anchor="w", pady=(0, 8))
        for line in ["SV001,Sinh Vien 1,KTPM", "SV002,Sinh Vien 2,KTPM", "SV003,Sinh Vien 3,KTPM"]:
            students_box.insert(END, line)

        student_line = StringVar()
        Entry(request_tab, textvariable=student_line, width=58).pack(side=LEFT, padx=(0, 8))

        def add_student_line() -> None:
            if student_line.get().strip():
                students_box.insert(END, student_line.get().strip())
                student_line.set("")

        Button(request_tab, text="Them sinh vien", command=add_student_line).pack(side=LEFT)

        def create_request() -> None:
            students = []
            for index in range(students_box.size()):
                parts = [part.strip() for part in students_box.get(index).split(",")]
                if len(parts) < 2:
                    continue
                students.append(
                    {
                        "student_code": parts[0],
                        "full_name": parts[1],
                        "class_label": parts[2] if len(parts) > 2 else class_code.get(),
                    }
                )
            payload = {
                "class_code": class_code.get(),
                "class_name": class_name.get(),
                "teacher_name": teacher_name.get(),
                "students": students,
                "expected_start_time": start_time.get(),
                "planned_end_time": end_time.get(),
                "late_grace_minutes": int(grace.get() or 0),
            }
            try:
                result = self.api.post_json("/attendance-requests", payload)
            except Exception as exc:
                messagebox.showerror("Create request failed", str(exc))
                return
            messagebox.showinfo("Created", f"Da tao yeu cau diem danh session #{result['session_id']}")

        Button(request_tab, text="Tao va gui yeu cau", command=create_request).pack(anchor="w", pady=14)

        import_status = StringVar(value="Chua import")
        Label(import_tab, text="Ten file bat dau bang MSSV. Vi du: SV001.jpg, SV001_1.jpg").pack(anchor="w")
        Label(import_tab, textvariable=import_status, fg="#475467").pack(anchor="w", pady=8)

        def import_face_paths(paths: list[Path]) -> None:
            if not paths:
                return
            try:
                result = self.api.post_files("/admin/face-import", paths)
            except Exception as exc:
                messagebox.showerror("Import failed", str(exc))
                return
            import_status.set(f"Imported {result['imported']}, failed {result['failed']}")
            details = "\n".join(f"{item['filename']}: {item['status']} - {item['detail']}" for item in result["items"])
            messagebox.showinfo("Import result", details[:3000])

        def import_faces() -> None:
            selected = filedialog.askopenfilenames(
                title="Chon anh sinh vien",
                filetypes=[("Image files", "*.jpg *.jpeg *.png"), ("All files", "*.*")],
            )
            import_face_paths([Path(item) for item in selected])

        def import_face_folder() -> None:
            selected_dir = filedialog.askdirectory(title="Chon folder anh sinh vien")
            if not selected_dir:
                return
            folder = Path(selected_dir)
            image_paths = sorted(
                item
                for item in folder.iterdir()
                if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg", ".png"}
            )
            if not image_paths:
                messagebox.showwarning("No images", "Folder khong co file .jpg, .jpeg hoac .png")
                return
            import_face_paths(image_paths)

        Button(import_tab, text="Chon anh va import", command=import_faces).pack(anchor="w", pady=8)
        Button(import_tab, text="Chon folder va import", command=import_face_folder).pack(anchor="w", pady=4)
        Button(import_tab, text="Dang xuat", command=self._build_login).pack(anchor="w", pady=18)

        student_table = ttk.Treeview(
            students_tab,
            columns=("id", "code", "name", "class", "faces", "image_url"),
            show="headings",
            height=22,
        )
        for key, text, width in [
            ("id", "ID", 60),
            ("code", "MSSV", 120),
            ("name", "Ho ten", 220),
            ("class", "Lop", 120),
            ("faces", "So anh", 80),
            ("image_url", "Anh gan nhat", 260),
        ]:
            student_table.heading(key, text=text)
            student_table.column(key, width=width)
        student_table.pack(fill=BOTH, expand=True, pady=(0, 10))

        def load_students() -> None:
            try:
                data = self.api.get("/admin/students/faces")
            except Exception as exc:
                messagebox.showerror("Load failed", str(exc))
                return
            student_table.delete(*student_table.get_children())
            for item in data:
                student_table.insert(
                    "",
                    END,
                    values=(
                        item["id"],
                        item["student_code"],
                        item["full_name"],
                        item["class_label"] or "",
                        item["face_template_count"],
                        item["latest_image_url"] or "",
                    ),
                )

        def open_selected_face() -> None:
            selected = student_table.selection()
            if not selected:
                messagebox.showwarning("Chua chon", "Hay chon mot sinh vien")
                return
            values = student_table.item(selected[0], "values")
            image_url = values[5]
            if not image_url:
                messagebox.showinfo("Khong co anh", "Sinh vien nay chua co anh khuon mat")
                return
            try:
                image_bytes = self.api.download_bytes(image_url)
                import numpy as np

                image_array = np.frombuffer(image_bytes, dtype=np.uint8)
                image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
                if image is None:
                    raise RuntimeError("Khong doc duoc anh")
                window_name = f"{values[1]} - {values[2]}"
                cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(window_name, 400, 600)
                cv2.imshow(window_name, image)
                cv2.waitKey(1)
            except Exception as exc:
                messagebox.showerror("Open image failed", str(exc))

        Button(students_tab, text="Tai danh sach sinh vien", command=load_students).pack(side=LEFT, padx=(0, 8))
        Button(students_tab, text="Xem anh chan dung", command=open_selected_face).pack(side=LEFT, padx=(0, 8))
        Button(students_tab, text="Dang xuat", command=self._build_login).pack(side=LEFT)

    def _build_user(self) -> None:
        self._clear()
        left = Frame(self.root, padx=12, pady=12)
        right = Frame(self.root, padx=12, pady=12)
        left.pack(side=LEFT, fill=BOTH)
        right.pack(side=RIGHT, fill=BOTH, expand=True)

        Label(left, text=f"Device: {self.api.full_name}", font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 10))
        requests_box = Listbox(left, height=14, width=50)
        requests_box.pack(anchor="w")
        request_map: dict[int, dict] = {}

        status = StringVar(value="San sang")
        Label(left, textvariable=status, fg="#475467", wraplength=360).pack(anchor="w", pady=10)

        board = ttk.Treeview(
            right,
            columns=("code", "name", "class", "time", "status", "alert"),
            show="headings",
            height=24,
        )
        for key, text in [
            ("code", "Ma"),
            ("name", "Ho ten"),
            ("class", "Lop"),
            ("time", "Thoi gian"),
            ("status", "Trang thai"),
            ("alert", "Thong bao"),
        ]:
            board.heading(key, text=text)
            board.column(key, width=120)
        board.pack(fill=BOTH, expand=True)

        def refresh_requests() -> None:
            try:
                data = self.api.get("/attendance-requests/open")
            except Exception as exc:
                status.set(str(exc))
                return
            requests_box.delete(0, END)
            request_map.clear()
            for item in data:
                request_map[item["session_id"]] = item
                requests_box.insert(
                    END,
                    f"#{item['session_id']} {item['class_code']} - {item['class_name']} ({item['student_count']} SV)",
                )
            status.set(f"Da tai {len(data)} yeu cau")

        def selected_session_id() -> int | None:
            selected = requests_box.curselection()
            if not selected:
                return None
            text = requests_box.get(selected[0])
            return int(text.split(" ", 1)[0].replace("#", ""))

        def refresh_board() -> None:
            session_id = self.active_session_id or selected_session_id()
            if session_id is None:
                return
            try:
                data = self.api.get(f"/sessions/{session_id}/attendance-board")
            except Exception as exc:
                status.set(str(exc))
                return
            board.delete(*board.get_children())
            for row in data["rows"]:
                recorded_at = row["recorded_at"] or ""
                if recorded_at:
                    recorded_at = recorded_at.split("T")[-1].split(".")[0]
                board.insert(
                    "",
                    END,
                    values=(
                        row["student_code"],
                        row["full_name"],
                        row["class_label"] or "",
                        recorded_at,
                        row["status"],
                        row["alert"],
                    ),
                )

        def start_attendance() -> None:
            session_id = selected_session_id()
            if session_id is None:
                messagebox.showwarning("Chua chon", "Hay chon yeu cau diem danh")
                return
            self.active_session_id = session_id
            refresh_board()
            if self.camera_running:
                return
            self.camera_running = True
            threading.Thread(target=self._camera_loop, args=(session_id, status, refresh_board), daemon=True).start()

        Button(left, text="Tai yeu cau", command=refresh_requests).pack(anchor="w", pady=(10, 4))
        Button(left, text="Bat dau diem danh", command=start_attendance).pack(anchor="w", pady=4)
        Button(left, text="Lam moi bang", command=refresh_board).pack(anchor="w", pady=4)
        Button(left, text="Dung camera", command=self._stop_camera).pack(anchor="w", pady=4)
        Button(left, text="Dang xuat", command=self._build_login).pack(anchor="w", pady=16)
        refresh_requests()

    def _camera_loop(self, session_id: int, status: StringVar, refresh_board) -> None:
        self.capture = cv2.VideoCapture(0)
        if not self.capture.isOpened():
            status.set("Khong mo duoc camera")
            self.camera_running = False
            return
        last_scan = 0.0
        while self.camera_running:
            ok, frame = self.capture.read()
            if not ok:
                status.set("Khong doc duoc frame camera")
                time.sleep(1)
                continue
            cv2.imshow("Attendance Camera", frame)
            if time.time() - last_scan >= 1.4:
                last_scan = time.time()
                ok, encoded = cv2.imencode(".jpg", frame)
                if ok:
                    payload = {
                        "camera_id": f"desktop-{self.api.user_id}",
                        "image_base64": base64.b64encode(encoded.tobytes()).decode("ascii"),
                        "idempotency_key": f"desktop-{uuid.uuid4()}",
                    }
                    try:
                        result = self.api.post_json(f"/sessions/{session_id}/scan-frame", payload)
                        if result["decision"] == "recognized":
                            status.set(
                                f"{result['full_name']} ({result['student_code']}) - {result['class_name']} - {result['message']}"
                            )
                            refresh_board()
                        else:
                            status.set(result["message"])
                    except Exception as exc:
                        status.set(str(exc))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        self._stop_camera()

    def _stop_camera(self) -> None:
        self.camera_running = False
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        cv2.destroyAllWindows()

    @staticmethod
    def _default_time(hour: int) -> str:
        value = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
        if hour < datetime.now().hour:
            value = value + timedelta(days=1)
        return value.isoformat()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
