from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from backend.app.models import ClassEnrollment, Student
from test_student_import import import_context as import_context
from test_web_ui import browser_page as browser_page


def serve_students(page, client):
    root = Path(__file__).resolve().parents[1] / "frontend"
    uploads = []

    def handle(route):
        request = route.request
        url = urlsplit(request.url)
        if url.path == "/demo/students":
            route.fulfill(path=str(root / "students.html"), content_type="text/html")
        elif url.path.startswith("/demo/assets/"):
            name = url.path.rsplit("/", 1)[1]
            route.fulfill(path=str(root / name), content_type="text/javascript" if name.endswith(".js") else "text/css")
        else:
            assert request.headers.get("authorization") == "Bearer test-token"
            headers = {"Content-Type": request.headers["content-type"]} if "content-type" in request.headers else {}
            response = client.request(request.method, url.path + ("?" + url.query if url.query else ""),
                                      content=request.post_data_buffer, headers=headers)
            if url.path == "/students/import":
                uploads.append(response.json())
            route.fulfill(status=response.status_code, body=response.content,
                          headers={key: value for key, value in response.headers.items() if key != "content-length"})

    page.route("http://localhost/**", handle)
    page.goto("http://localhost/demo/students")
    return uploads


def test_preview_import_and_class_change_use_real_api_without_writing_local_database(browser_page, import_context):
    page, expect = browser_page
    client, db, class_, _ = import_context
    uploads = serve_students(page, client)
    page.locator("#openStudentImport").click()
    expect(page.locator("#studentImportDialog")).to_be_visible()
    expect(page.locator("#confirmStudentImport")).to_be_disabled()
    content = "MSSV,Họ và tên,Lớp\n00123,Nguyễn Văn An,KTPM\n00123,Duplicate,KTPM\nBAD,,KTPM\n".encode()
    page.locator("#studentImportFile").set_input_files({"name": "students.csv", "mimeType": "text/csv", "buffer": content})
    page.locator("#previewStudentImport").click()
    expect(page.locator("#studentImportSummary")).to_have_text("3 dòng · 1 hợp lệ · 1 trùng · 1 lỗi")
    expect(page.locator("#confirmStudentImport")).to_be_enabled()
    assert db.scalar(select(Student)) is None
    page.locator("#studentImportClass").select_option(str(class_.id))
    expect(page.locator("#confirmStudentImport")).to_be_disabled()
    expect(page.locator("#studentImportResults")).to_be_hidden()
    page.locator("#previewStudentImport").click()
    expect(page.locator("#confirmStudentImport")).to_be_enabled()
    page.locator("#confirmStudentImport").click()
    expect(page.locator("#studentImportSummary")).to_have_text("Đã thêm 1 sinh viên · 1 trùng đã bỏ qua · 1 dòng lỗi")
    expect(page.locator("#confirmStudentImport")).to_be_disabled()
    expect(page.locator("#studentCount")).to_have_text("1 / 1 sinh viên")
    assert db.scalar(select(Student)).student_code == "00123"
    assert db.scalar(select(ClassEnrollment)).class_id == class_.id
    assert sum(not result["dry_run"] for result in uploads) == 1
    page.locator("#closeStudentImport").click()
    expect(page.locator("#studentsTable")).to_contain_text("Nguyễn Văn An")


def test_excel_template_download_and_file_errors_stay_inside_dialog(browser_page, import_context, tmp_path):
    page, expect = browser_page
    client, *_ = import_context
    uploads = serve_students(page, client)
    page.locator("#openStudentImport").click()
    with page.expect_download() as download:
        page.locator('[data-student-template="xlsx"]').click()
    assert download.value.suggested_filename == "mau-sinh-vien.xlsx"
    path = tmp_path / "template.xlsx"
    download.value.save_as(path)
    page.locator("#studentImportFile").set_input_files({"name": "template.xlsx",
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": path.read_bytes()})
    page.locator("#previewStudentImport").click()
    expect(page.locator("#studentImportSummary")).to_have_text("1 dòng · 1 hợp lệ · 0 trùng · 0 lỗi")
    page.locator("#studentImportFile").set_input_files({"name": "bad.csv", "mimeType": "text/csv", "buffer": b"wrong,headers\nA,Name\n"})
    page.locator("#previewStudentImport").click()
    expect(page.locator("#studentImportNotice")).to_contain_text("Cần cột MSSV")
    expect(page.locator("#confirmStudentImport")).to_be_disabled()
    expect(page.locator("#studentImportResults")).to_be_hidden()
    assert all(result.get("dry_run", True) for result in uploads)
