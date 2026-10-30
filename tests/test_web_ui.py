"""Kiểm tra UI bằng webcam tổng hợp, không truy cập camera/người thật."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def browser_page(request):
    if not request.config.getoption("--run-browser"):
        pytest.skip("Use --run-browser and install requirements-browser.txt")
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="chrome", headless=True, args=[
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        ])
        context = browser.new_context(permissions=["camera"])
        context.add_init_script("""sessionStorage.setItem('face-attendance-account', JSON.stringify({
          user_id: 1, role: 'admin', full_name: 'Test Admin'
        }));""")
        page = context.new_page()
        yield page, playwright.expect
        context.close()
        browser.close()


def serve_ui(page, *, ready=True, passed=False, status_error=False, recorded=True, readiness_message=None,
             transient_miss=False, challenge_starts=None):
    root = Path(__file__).resolve().parents[1] / "frontend"
    scans = []

    def handle(route):
        request = route.request
        path = request.url.split("localhost", 1)[1].split("?", 1)[0]
        if path == "/demo/attendance":
            route.fulfill(path=str(root / "attendance.html"), content_type="text/html")
            return
        if path.startswith("/demo/assets/"):
            name = path.rsplit("/", 1)[1]
            route.fulfill(path=str(root / name), content_type="text/javascript" if name.endswith(".js") else "text/css")
            return
        if path == "/face-analysis/status":
            if status_error:
                route.fulfill(status=503, json={"detail": "PAD unavailable"})
                return
            body = {"web_liveness_required": True, "web_liveness_ready": ready,
                    "web_liveness_message": readiness_message}
        elif path == "/attendance-requests/open":
            body = [{"session_id": 1, "class_code": "TEST01", "class_name": "Test Class",
                     "expected_start_time": "2026-10-29T13:00:00Z", "late_grace_minutes": 5}]
        elif path.endswith("/attendance-board"):
            body = {"rows": [{"student_id": 1, "student_code": "TEST001", "full_name": "Synthetic Test",
                              "class_label": "TEST01", "status": "pending", "recorded_at": None, "alert": ""}]}
        elif path.endswith("/liveness-challenge"):
            if challenge_starts is not None:
                challenge_starts.append(True)
            body = {"status": "pending", "challenge_id": "test-id", "step_token": "nonce-0",
                    "sequence": 0, "action": "center", "step": 0, "total_steps": 7,
                    "message": "Nhìn thẳng và giữ yên khuôn mặt"}
        elif path.endswith("/scan-frame"):
            payload = request.post_data_json
            scans.append({key: payload.get(key) for key in ("challenge_id", "step_token", "sequence")})
            if passed:
                body = {"decision": "recognized", "student_code": "TEST001", "full_name": "Synthetic Test",
                        "message": "Đúng giờ" if recorded else "Chưa lưu điểm danh", "face_box": [200, 100, 100, 140],
                        "attendance": {"id": 1} if recorded else None,
                        "liveness": {"status": "passed", "message": "Đã xác minh người thật"}}
            else:
                body = {"decision": "unknown", "message": "Quay đầu nhẹ sang phải của bạn", "face_box": [200, 100, 100, 140],
                        "liveness": {"status": "pending", "challenge_id": "test-id", "step_token": "nonce-1",
                                     "sequence": len(scans), "step": 1, "total_steps": 7, "action": "right"}}
                if transient_miss and len(scans) == 2:
                    body["message"] = "Tạm mất khuôn mặt; quay đầu chậm và giảm góc quay"
                    body["face_box"] = None
        else:
            route.fulfill(status=404, json={"detail": "Unexpected test route"})
            return
        route.fulfill(body=json.dumps(body), content_type="application/json")

    page.route("http://localhost/**", handle)
    page.goto("http://localhost/demo/attendance?session=1")
    return scans


def test_web_displays_server_action_and_sends_fresh_state_without_identity(browser_page):
    page, expect = browser_page
    scans = serve_ui(page)
    expect(page.locator("#activeSession")).to_have_value("1")
    page.locator("#scanToggle").click()
    expect(page.locator("#livenessHint")).to_have_text("Quay đầu nhẹ sang phải của bạn")
    expect(page.locator("#scanFaceLabel")).to_be_hidden()
    expect(page.locator("#livenessProgress")).to_have_attribute("value", "1")
    # Chờ frame thứ hai để kiểm tra client dùng nonce/sequence mới từ server.
    page.wait_for_function("document.querySelector('#scanLog').children.length >= 2")
    page.locator("#scanToggle").click()
    assert scans[0] == {"challenge_id": "test-id", "step_token": "nonce-0", "sequence": 0}
    assert scans[1] == {"challenge_id": "test-id", "step_token": "nonce-1", "sequence": 1}


@pytest.mark.parametrize("status_error", [False, True])
def test_unavailable_pad_blocks_scanning_but_manual_controls_still_work(browser_page, status_error):
    page, expect = browser_page
    scans = serve_ui(page, ready=False, status_error=status_error)
    expect(page.locator("#activeSession")).to_have_value("1")
    page.locator("#scanToggle").click()
    expect(page.locator("#notice")).to_contain_text("chống giả mạo chưa sẵn sàng")
    assert scans == []
    page.locator('[data-manual="1"]').click()
    expect(page.locator("#manualDialog")).to_be_visible()


def test_web_explains_disabled_backend_configuration(browser_page):
    page, expect = browser_page
    scans = serve_ui(page, ready=False, readiness_message="Backend chưa bật LIVENESS_MODE=enforce; hãy mở lại terminal.")
    expect(page.locator("#livenessHint")).to_contain_text("LIVENESS_MODE=enforce")
    assert scans == []


def test_web_only_shows_identity_after_server_reports_passed_and_recorded(browser_page):
    page, expect = browser_page
    scans = serve_ui(page, passed=True)
    expect(page.locator("#activeSession")).to_have_value("1")
    page.locator("#scanToggle").click()
    expect(page.locator("#livenessTitle")).to_have_text("Đã ghi nhận điểm danh")
    expect(page.locator("#livenessHint")).to_contain_text("TEST001 · Synthetic Test")
    expect(page.locator("#scanToggle")).to_have_text("Quét người tiếp theo")
    expect(page.locator("#scanFaceBox")).to_be_hidden()
    expect(page.locator("#scanLog")).to_contain_text("TEST001")
    page.wait_for_timeout(1600)  # More than two scan intervals after completion.
    assert len(scans) == 1


def test_web_does_not_show_success_for_unsaved_attendance(browser_page):
    page, expect = browser_page
    serve_ui(page, passed=True, recorded=False)
    expect(page.locator("#activeSession")).to_have_value("1")
    page.locator("#scanToggle").click()
    expect(page.locator("#scanLog")).to_contain_text("Chưa lưu điểm danh")
    expect(page.locator("#scanFaceLabel")).to_be_hidden()
    page.locator("#scanToggle").click()


def test_web_keeps_challenge_and_sequence_after_transient_face_miss(browser_page):
    page, expect = browser_page
    starts = []
    scans = serve_ui(page, transient_miss=True, challenge_starts=starts)
    expect(page.locator("#activeSession")).to_have_value("1")
    page.locator("#scanToggle").click()
    page.wait_for_function("document.querySelector('#scanLog').children.length >= 3")
    page.locator("#scanToggle").click()
    assert len(starts) == 1
    assert [scan["challenge_id"] for scan in scans[:3]] == ["test-id"] * 3
    assert [scan["sequence"] for scan in scans[:3]] == [0, 1, 2]
    expect(page.locator("#scanLog")).to_contain_text("Tạm mất khuôn mặt")
    expect(page.locator("#scanFaceLabel")).to_be_hidden()
