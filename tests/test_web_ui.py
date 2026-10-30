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
        context = browser.new_context(permissions=["camera"], timezone_id="Asia/Ho_Chi_Minh")
        context.add_init_script("""sessionStorage.setItem('face-attendance-account', JSON.stringify({
          access_token: 'test-token', user_id: 1, role: 'admin', full_name: 'Test Admin'
        }));""")
        context.add_init_script("""
          // Deterministic live frames: stable scene plus a changing corner marker.
          window.testCameraColor = '#a8917c';
          navigator.mediaDevices.getUserMedia = async () => {
            const canvas = document.createElement('canvas');
            canvas.width = 640; canvas.height = 480;
            const ctx = canvas.getContext('2d');
            let number = 0;
            const paint = () => {
              ctx.fillStyle = window.testCameraColor; ctx.fillRect(0, 0, 640, 480);
              ctx.fillStyle = `rgb(${number++ % 255}, 0, 0)`; ctx.fillRect(0, 0, 5, 5);
            };
            paint(); setInterval(paint, 40);
            return canvas.captureStream(25);
          };
        """)
        page = context.new_page()
        yield page, playwright.expect
        context.close()
        browser.close()


def serve_ui(page, *, recognized=False, recorded=True, transient_miss=False, unexpected=None, scene=None,
             start_time="2026-10-29T13:00:00Z", readiness=None, policy_updates=None):
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
        if path == "/attendance-requests/open":
            body = [{"session_id": 1, "class_code": "TEST01", "class_name": "Test Class",
                     "expected_start_time": start_time, "late_grace_minutes": 5}]
        elif path.endswith("/face-readiness"):
            body = readiness or {"ready": 1, "total": 1, "engine_ready": True}
        elif path.endswith("/policy") and request.method == "PUT":
            if policy_updates is not None:
                policy_updates.append(request.post_data_json)
            body = request.post_data_json
        elif path.endswith("/attendance-board"):
            body = {"rows": [{"student_id": 1, "student_code": "TEST001", "full_name": "Synthetic Test",
                              "class_label": "TEST01", "status": "pending", "recorded_at": None, "alert": ""}]}
        elif path.endswith("/scan-stream"):
            scans.append(request.post_data_json)
            if recognized:
                body = {"decision": "recognized", "student_code": "TEST001", "full_name": "Synthetic Test",
                        "message": "Đúng giờ" if recorded else "Chưa lưu điểm danh", "face_box": [200, 100, 100, 140],
                        "attendance": {"id": 1} if recorded else None}
            else:
                body = {"decision": "unknown", "message": "Độ tin cậy chưa đủ, vui lòng nhìn thẳng vào camera",
                        "face_box": [200, 100, 100, 140]}
                if transient_miss and len(scans) == 2:
                    body["message"] = "Không phát hiện khuôn mặt"
                    body["face_box"] = None
            body["track_id"] = "face-one"
            faces = [body] if body.get("face_box") else []
            if scene is not None:
                faces = scene(request.post_data_json["frame_id"])
            body = {"frame_id": request.post_data_json["frame_id"], "frame_width": 640, "frame_height": 480,
                    "faces": faces, "message": body["message"], "processing_ms": 100, "next_frame_delay_ms": 150}
        else:
            if unexpected is not None:
                unexpected.append(path)
            route.fulfill(status=404, json={"detail": "Unexpected test route"})
            return
        route.fulfill(body=json.dumps(body), content_type="application/json")

    page.route("http://localhost/**", handle)
    page.goto("http://localhost/demo/attendance?session=1")
    return scans


def start_scan(page):
    page.locator("#scanToggle").click()
    # Fake Chrome cameras may need longer than an assertion timeout to start.
    # Wait for actual video readiness before checking response/UI semantics.
    page.wait_for_function("document.querySelector('#scanVideo').readyState >= 2 && "
                           "document.querySelector('#scanVideo').videoWidth > 0", timeout=15000)


def test_web_scans_directly_without_pad_or_challenge_services(browser_page):
    page, expect = browser_page
    unexpected = []
    scans = serve_ui(page, unexpected=unexpected)
    expect(page.locator("#activeSession")).to_have_value("1")
    start_scan(page)
    expect(page.locator("#scanFeedback")).to_contain_text("Độ tin cậy chưa đủ")
    expect(page.locator("#scanFaces .scan-face-box")).to_be_visible()
    expect(page.locator("#scanFaces .scan-face-name")).to_have_text("Đang nhận diện")
    expect(page.locator("#scanFaces .scan-face-box")).to_have_css("border-top-color", "rgb(242, 201, 107)")
    page.wait_for_timeout(600)
    page.locator("#scanToggle").click()
    assert scans[0]["image_base64"].startswith("data:image/")
    assert not {"challenge_id", "step_token", "sequence", "student_id"} & scans[0].keys()
    assert unexpected == []
    assert len(scans) >= 2 and scans[0]["frame_id"] == 0 and scans[1]["frame_id"] == 1
    assert scans[0]["stream_id"] == scans[1]["stream_id"]
    expect(page.locator("#scanLog .muted")).to_be_visible()


def test_manual_controls_still_work_without_scanning(browser_page):
    page, expect = browser_page
    scans = serve_ui(page)
    expect(page.locator("#activeSession")).to_have_value("1")
    page.locator('[data-manual="1"]').click()
    expect(page.locator("#manualDialog")).to_be_visible()
    assert scans == []


def test_policy_uses_utc_storage_and_roundtrips_local_time(browser_page):
    page, expect = browser_page
    updates = []
    serve_ui(page, start_time="2026-10-31T00:00:00", policy_updates=updates)
    expect(page.locator("#policyStart")).to_have_value("2026-10-31T07:00")
    page.locator("#savePolicy").click()
    expect(page.locator("#notice")).to_contain_text("Đã cập nhật")
    assert updates[0]["expected_start_time"] == "2026-10-31T00:00:00.000Z"
    page.reload()
    expect(page.locator("#policyStart")).to_have_value("2026-10-31T07:00")


def test_readiness_warning_and_camera_controls_do_not_stop_manual_attendance(browser_page):
    page, expect = browser_page
    serve_ui(page, readiness={"ready": 0, "total": 5, "engine_ready": True})
    expect(page.locator("#faceReadiness")).to_contain_text("0/5 sinh viên có Face ID hợp lệ")
    expect(page.locator("#faceReadiness a")).to_have_attribute("href", "/demo/faces")
    start_scan(page)
    expect(page.locator("#scanCamera")).to_have_text("Tắt camera")
    page.locator("#scanToggle").click()
    expect(page.locator("#scanFeedback")).to_contain_text("Đã dừng quét")
    page.evaluate("window.cameraTrack = document.querySelector('#scanVideo').srcObject.getVideoTracks()[0]")
    page.locator("#scanCamera").click()
    assert page.evaluate("window.cameraTrack.readyState") == "ended"
    expect(page.locator("#scanCamera")).to_have_text("Bật camera")
    page.locator('[data-manual="1"]').click()
    expect(page.locator("#manualDialog")).to_be_visible()


def test_browser_login_uses_bearer_and_logout_revokes_session(browser_page):
    original, expect = browser_page
    context = original.context.browser.new_context()
    page = context.new_page()
    root = Path(__file__).resolve().parents[1] / "frontend"
    calls = []

    def handle(route):
        request = route.request
        path = request.url.split("localhost", 1)[1]
        if path in {"/demo/login", "/demo"}:
            route.fulfill(path=str(root / ("login.html" if path.endswith("login") else "attendance.html")),
                          content_type="text/html")
        elif path.startswith("/demo/assets/"):
            name = path.rsplit("/", 1)[1]
            route.fulfill(path=str(root / name), content_type="text/javascript" if name.endswith(".js") else "text/css")
        elif path == "/auth/login-json":
            assert request.post_data_json == {"username": "admin", "password": "admin123"}
            route.fulfill(json={"access_token": "browser-token", "user_id": 1, "role": "admin", "full_name": "Admin"})
        elif path == "/attendance-requests/open":
            assert request.headers.get("authorization") == "Bearer browser-token"
            assert "x-user-id" not in request.headers
            calls.append("authenticated")
            route.fulfill(json=[])
        elif path == "/auth/logout":
            assert request.headers.get("authorization") == "Bearer browser-token"
            calls.append("logout")
            route.fulfill(status=204)
        else:
            route.fulfill(status=404, json={"detail": "Unexpected test route"})

    try:
        page.route("http://localhost/**", handle)
        page.goto("http://localhost/demo/login")
        page.locator("#username").fill("admin")
        page.locator("#password").fill("admin123")
        page.locator('#loginForm button[type="submit"]').click()
        expect(page.locator("#logout")).to_be_visible()
        expect(page.locator("#activeSession")).to_be_visible()
        page.locator("#logout").click()
        expect(page).to_have_url("http://localhost/demo/login")
        assert page.evaluate("sessionStorage.getItem('face-attendance-account')") is None
        assert calls == ["authenticated", "logout"]
    finally:
        context.close()


def test_saved_attendance_keeps_streaming_and_logs_each_person_once(browser_page):
    page, expect = browser_page
    scans = serve_ui(page, recognized=True)
    expect(page.locator("#activeSession")).to_have_value("1")
    start_scan(page)
    expect(page.locator("#scanToggle")).to_have_text("Dừng quét")
    expect(page.locator("#scanBadge")).to_contain_text("Đang quét")
    expect(page.locator("#scanLog")).to_contain_text("TEST001")
    expect(page.locator("#scanFaces .scan-face-box")).to_be_visible()
    expect(page.locator("#scanFaces .scan-face-box")).to_have_css("border-top-color", "rgb(85, 224, 187)")
    expect(page.locator("#scanFaces .scan-face-name")).to_have_text("Synthetic Test")
    expect(page.locator("#scanSnapshot")).to_have_count(0)
    face, label = page.locator("#scanFaces .scan-face-box").bounding_box(), page.locator("#scanFaces .scan-face-label").bounding_box()
    assert label["y"] + label["height"] <= face["y"]
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(250)
    face, label = page.locator("#scanFaces .scan-face-box").bounding_box(), page.locator("#scanFaces .scan-face-label").bounding_box()
    assert label["y"] + label["height"] <= face["y"]
    page.wait_for_timeout(1000)
    assert len(scans) >= 3
    expect(page.locator("#scanLog li")).to_have_count(1)
    page.locator("#scanToggle").click()
    expect(page.locator("#scanFaces .scan-face-box")).to_have_count(0)


def test_web_does_not_show_success_for_unsaved_attendance(browser_page):
    page, expect = browser_page
    serve_ui(page, recognized=True, recorded=False)
    expect(page.locator("#activeSession")).to_have_value("1")
    start_scan(page)
    expect(page.locator("#scanFeedback")).to_contain_text("Chưa lưu điểm danh")
    expect(page.locator("#scanLog .muted")).to_be_visible()
    expect(page.locator("#scanFaces .scan-face-name")).to_have_text("Đang nhận diện")
    expect(page.locator("#scanFaces .scan-face-box")).to_have_css("border-top-color", "rgb(242, 201, 107)")
    expect(page.locator("#scanBadge")).to_contain_text("Đang quét")
    page.locator("#scanToggle").click()


def test_web_keeps_scanning_after_transient_face_miss(browser_page):
    page, expect = browser_page
    unexpected = []
    scans = serve_ui(page, transient_miss=True, unexpected=unexpected)
    expect(page.locator("#activeSession")).to_have_value("1")
    start_scan(page)
    page.wait_for_timeout(1100)
    page.locator("#scanToggle").click()
    assert len(scans) >= 3 and unexpected == []
    expect(page.locator("#scanFaces .scan-face-box")).to_have_count(0)


def test_stream_allows_only_one_inflight_frame_and_manual_stop_ignores_late_response(browser_page):
    page, expect = browser_page
    serve_ui(page, recognized=True)
    pending = []
    page.route("**/sessions/1/scan-stream", lambda route: pending.append(route))
    start_scan(page)
    expect(page.locator("#scanGuide")).to_be_visible()
    expect(page.locator("#scanGuide")).to_have_css("border-top-color", "rgb(242, 201, 107)")
    page.wait_for_function("document.querySelector('#scanToggle').textContent === 'Dừng quét'")
    page.wait_for_timeout(800)
    assert len(pending) == 1
    page.locator("#scanToggle").click()
    pending[0].fulfill(json={"frame_id": 0, "frame_width": 640, "frame_height": 480,
                             "faces": [], "message": "Late result"})
    page.wait_for_timeout(400)
    expect(page.locator("#scanFaces .scan-face-box")).to_have_count(0)
    expect(page.locator("#scanGuide")).to_be_hidden()
    expect(page.locator("#scanToggle")).to_have_text("Bắt đầu quét")
    assert len(pending) == 1


def test_recognized_name_stays_readable_at_top_edge_on_mobile_and_is_plain_text(browser_page):
    page, expect = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    name = "Nguyễn Thị Minh Anh <img src=x>"
    serve_ui(page, scene=lambda _: [{
        "decision": "recognized", "student_code": "TEST001", "full_name": name,
        "face_box": [0, 5, 180, 180], "attendance": {"id": 1}, "message": "Đúng giờ", "track_id": "mobile",
    }])
    start_scan(page)
    expect(page.locator("#scanFaces .scan-face-name")).to_have_text(name)
    expect(page.locator("#scanFaces .scan-face-box")).to_have_class("scan-face-box recognized label-inside")
    expect(page.locator("#scanFaces .scan-face-label img")).to_have_count(0)
    # Wait for the existing box position transition to settle before measuring.
    page.wait_for_timeout(250)
    camera = page.locator("#attendanceCamera").bounding_box()
    label = page.locator("#scanFaces .scan-face-label").bounding_box()
    assert label["x"] >= camera["x"]
    assert label["x"] + label["width"] <= camera["x"] + camera["width"]
    assert label["y"] >= camera["y"]
    page.locator("#scanToggle").click()


def test_crowd_stream_keeps_pending_people_accepts_new_arrivals_and_removes_departed_boxes(browser_page):
    page, expect = browser_page
    state = {"phase": 0}

    def face(track, name, x, recorded):
        return {"track_id": track, "face_box": [x, 100, 100, 140],
                "decision": "recognized" if recorded else "pending", "full_name": name if recorded else None,
                "student_code": track, "attendance": {"id": track} if recorded else None,
                "message": "Đúng giờ" if recorded else "Đang xác nhận", "confirmation_hits": 1, "confirmation_required": 3}

    def scene(_frame_id):
        if state["phase"] == 0:
            return [face("A", "Nguyễn An", 80, True), face("B", "Trần Bình", 260, False)]
        return [face("B", "Trần Bình", 260, state["phase"] == 2), face("C", "Lê Chi", 430, state["phase"] == 2)]

    scans = serve_ui(page, scene=scene)
    start_scan(page)
    expect(page.locator('#scanFaces [data-track-id="A"]')).to_have_css("border-top-color", "rgb(85, 224, 187)")
    expect(page.locator('#scanFaces [data-track-id="B"]')).to_have_css("border-top-color", "rgb(242, 201, 107)")
    expect(page.locator("#scanLog li")).to_have_count(1)
    state["phase"] = 1
    expect(page.locator('#scanFaces [data-track-id="A"]')).to_have_count(0)
    expect(page.locator('#scanFaces [data-track-id="C"]')).to_be_visible()
    state["phase"] = 2
    expect(page.locator('#scanFaces [data-track-id="B"] .scan-face-name')).to_have_text("Trần Bình")
    expect(page.locator('#scanFaces [data-track-id="C"] .scan-face-name')).to_have_text("Lê Chi")
    expect(page.locator("#scanLog li")).to_have_count(3)
    page.wait_for_timeout(800)
    expect(page.locator("#scanLog li")).to_have_count(3)
    expect(page.locator("#scanToggle")).to_have_text("Dừng quét")
    assert not page.locator("#scanVideo").evaluate("video => video.paused")
    assert len({item["stream_id"] for item in scans}) == 1
    page.locator("#scanToggle").click()


def test_stream_recovers_after_temporary_server_failure_without_user_restart(browser_page):
    page, expect = browser_page
    serve_ui(page, recognized=True)
    requests = []

    def fail_once(route):
        requests.append(True)
        if len(requests) == 1:
            route.fulfill(status=503, json={"detail": "Temporary model busy"})
        else:
            route.fallback()

    page.route("**/sessions/1/scan-stream", fail_once)
    start_scan(page)
    expect(page.locator("#scanFaces .scan-face-name")).to_have_text("Synthetic Test", timeout=10000)
    assert len(requests) >= 2
    expect(page.locator("#scanToggle")).to_have_text("Dừng quét")
    page.locator("#scanToggle").click()


def test_each_unrecognized_face_shows_its_own_guidance(browser_page):
    page, expect = browser_page
    def scene(_frame_id):
        return [{"track_id": "dark", "face_box": [45, 135, 110, 160], "decision": "unknown",
                 "message": "Khung hình quá tối, vui lòng tăng ánh sáng"},
                {"track_id": "small", "face_box": [300, 135, 110, 160], "decision": "unknown",
                 "message": "Khuôn mặt quá nhỏ, vui lòng tiến gần camera"}]
    serve_ui(page, scene=scene)
    start_scan(page)
    expect(page.locator('[data-track-id="dark"] .scan-face-code')).to_have_text("Tăng ánh sáng")
    expect(page.locator('[data-track-id="small"] .scan-face-code')).to_have_text("Tiến gần camera")
    page.locator("#scanToggle").click()


def test_mobile_crowd_labels_have_separate_slots(browser_page):
    page, expect = browser_page
    page.set_viewport_size({"width": 390, "height": 844})

    def scene(_frame_id):
        return [{"track_id": str(index), "face_box": [45 + index * 215, 135, 110, 160],
                 "decision": "recognized" if index != 1 else "pending", "full_name": "Nguyễn Văn Kiểm Thử",
                 "student_code": f"TEST{index}", "attendance": {"id": index + 1} if index != 1 else None,
                 "confirmation_hits": 2, "confirmation_required": 3, "message": "Đúng giờ"}
                for index in range(3)]

    serve_ui(page, scene=scene)
    start_scan(page)
    expect(page.locator("#scanFaces .scan-face-label")).to_have_count(3)
    labels = sorted(page.locator("#scanFaces .scan-face-label").evaluate_all(
        "labels => labels.map(label => { const r = label.getBoundingClientRect(); return {x: r.x, right: r.right}; })"),
        key=lambda label: label["x"])
    camera = page.locator("#attendanceCamera").bounding_box()
    assert labels[0]["x"] >= camera["x"]
    assert labels[-1]["right"] <= camera["x"] + camera["width"]
    assert all(left["right"] + 4 <= right["x"] for left, right in zip(labels, labels[1:]))
    page.locator("#scanToggle").click()


def test_changed_live_face_cannot_keep_the_previous_person_green_while_model_is_busy(browser_page):
    page, expect = browser_page
    serve_ui(page, recognized=True)
    pending = []

    def hold_after_first(route):
        if route.request.post_data_json["frame_id"] == 0:
            route.fallback()
        else:
            pending.append(route)

    page.route("**/sessions/1/scan-stream", hold_after_first)
    start_scan(page)
    expect(page.locator("#scanFaces .scan-face-name")).to_have_text("Synthetic Test")
    page.evaluate("window.testCameraColor = '#102030'")
    expect(page.locator("#scanFaces .scan-face-box")).to_have_css("border-top-color", "rgb(242, 201, 107)")
    expect(page.locator("#scanFaces .scan-face-name")).to_have_text("Đang nhận diện")
    expect(page.locator("#scanLog li")).to_have_count(1)
    page.locator("#scanToggle").click()


def serve_enrollment(page, *, accept=False, defer=False, fail=False, audio=True, consent="granted"):
    root = Path(__file__).resolve().parents[1] / "frontend"
    state = {"accept": accept, "scans": [], "captured": [], "pending": [], "resets": 0}
    if audio:
        page.add_init_script("""
          window.testBeeps = [];
          const NativeAudioContext = window.AudioContext;
          window.AudioContext = class extends NativeAudioContext {
            createOscillator() {
              const oscillator = super.createOscillator();
              const start = oscillator.start.bind(oscillator), stop = oscillator.stop.bind(oscillator);
              const entry = {};
              oscillator.start = (when = 0) => {
                Object.assign(entry, {frequency: oscillator.frequency.value, start: when, wall: performance.now()});
                window.testBeeps.push(entry);
                return start(when);
              };
              oscillator.stop = (when) => {
                if (when === undefined) entry.cancelled = true;
                else entry.duration = when - entry.start;
                return stop(when);
              };
              return oscillator;
            }
          };
        """)
    else:
        page.add_init_script("window.AudioContext = undefined; window.webkitAudioContext = undefined;")

    def handle(route):
        path = route.request.url.split("localhost", 1)[1].split("?", 1)[0]
        if path == "/demo/faces":
            route.fulfill(path=str(root / "faces.html"), content_type="text/html")
            return
        if path.startswith("/demo/assets/"):
            name = path.rsplit("/", 1)[1]
            route.fulfill(path=str(root / name), content_type="text/javascript" if name.endswith(".js") else "text/css")
            return
        if path == "/classes":
            body = []
        elif path == "/admin/students/faces":
            body = [{"id": 1, "student_code": "TEST001", "full_name": "Synthetic Test", "consent_status": consent,
                     "face_template_count": len(state["captured"]), "captured_pose_count": len(state["captured"]),
                     "enrollment_complete": len(state["captured"]) == 5}]
        elif path == "/face-enrollment/engine":
            body = {"available": True, "engine": "test-engine"}
        elif path.endswith("/face-enrollment/start"):
            state["resets"] += 1
            state["captured"].clear()
            body = {"enrollment_id": "a" * 32}
        elif path.endswith("/face-enrollment/draft"):
            route.fulfill(status=204)
            return
        elif path.endswith("/face-enrollment/scan"):
            payload = route.request.post_data_json
            state["scans"].append(payload)
            if defer:
                state["pending"].append(route)
                return
            if fail:
                route.fulfill(status=500, json={"detail": "Lỗi thử nghiệm"})
                return
            target = payload["target_pose"]
            if state["accept"] and target not in state["captured"]:
                state["captured"].append(target)
            body = {"accepted": state["accept"], "completed": len(state["captured"]) == 5,
                    "captured_poses": state["captured"].copy(), "pitch": 0,
                    "detected_pose": target, "message": "Đã ghi nhận góc khuôn mặt" if state["accept"] else "Hãy giữ đúng góc"}
        else:
            route.fulfill(status=404, json={"detail": "Unexpected test route: " + path})
            return
        route.fulfill(json=body)

    page.route("http://localhost/**", handle)
    page.goto("http://localhost/demo/faces?student=1")
    return state


def start_enrollment(page, expect):
    expect(page.locator("#faceStudent")).to_have_value("1")
    page.locator("#captureFace").click()
    page.wait_for_function("document.querySelector('#faceVideo').readyState >= 2 && "
                           "document.querySelector('#faceVideo').videoWidth > 0", timeout=15000)


def test_unconsented_student_link_explains_next_step(browser_page):
    page, expect = browser_page
    serve_enrollment(page, consent="pending")
    expect(page.locator("#notice")).to_contain_text("TEST001 chưa đồng ý")
    expect(page.locator("#notice")).to_contain_text("Quản lý sinh viên")
    expect(page.locator("#faceStudent")).to_have_value("")


def test_enrollment_repeats_short_beeps_and_stops_them_when_paused(browser_page):
    page, expect = browser_page
    state = serve_enrollment(page)
    start_enrollment(page, expect)
    page.wait_for_function("window.testBeeps.filter(b => b.duration < .2).length >= 3")
    assert state["scans"] and state["resets"] == 1
    assert not page.evaluate("window.testBeeps.some(b => b.duration > .5)")
    page.locator("#captureFace").click()
    expect(page.locator("#poseMessage")).to_contain_text("Đã tạm dừng")
    before = page.evaluate("window.testBeeps.length")
    page.wait_for_timeout(900)
    assert page.evaluate("window.testBeeps.length") == before


def test_enrollment_emits_one_long_beep_for_each_saved_angle_and_finishes_silently(browser_page):
    page, expect = browser_page
    state = serve_enrollment(page, accept=True)
    start_enrollment(page, expect)
    expect(page.locator("#cameraStep")).to_have_text("Hoàn tất", timeout=20000)
    expect(page.locator("#notice")).to_contain_text("Đã hoàn tất đăng ký Face ID")
    assert [item["target_pose"] for item in state["scans"]] == ["front", "left", "right", "up", "down"]
    beeps = page.evaluate("window.testBeeps")
    long_beeps = [beep for beep in beeps if beep.get("duration", 0) > 0.5]
    assert len(long_beeps) == 5
    assert all(abs(beep["duration"] - 0.65) < 0.001 for beep in long_beeps)
    assert not any(beep.get("cancelled") for beep in long_beeps)
    assert all(right["wall"] - left["wall"] >= 1900 for left, right in zip(long_beeps, long_beeps[1:]))
    before = len(beeps)
    page.wait_for_timeout(1100)
    assert page.evaluate("window.testBeeps.length") == before


def test_enrollment_mute_stops_sound_while_scanning_continues(browser_page):
    page, expect = browser_page
    state = serve_enrollment(page)
    start_enrollment(page, expect)
    page.wait_for_function("window.testBeeps.length >= 1")
    page.locator("#enrollSound").uncheck()
    before = page.evaluate("window.testBeeps.length")
    scan_count = len(state["scans"])
    page.wait_for_timeout(1200)
    assert page.evaluate("window.testBeeps.length") == before
    assert len(state["scans"]) > scan_count
    page.locator("#enrollSound").check()
    page.wait_for_function("window.testBeeps.length > " + str(before))
    page.locator("#captureFace").click()


def test_enrollment_unavailable_audio_does_not_prevent_capture(browser_page):
    page, expect = browser_page
    state = serve_enrollment(page, audio=False)
    start_enrollment(page, expect)
    expect(page.locator("#enrollSoundHint")).to_contain_text("Chưa phát được âm thanh")
    expect(page.locator("#poseMessage")).to_have_text("Hãy giữ đúng góc")
    assert state["scans"]
    page.locator("#captureFace").click()


def test_late_enrollment_response_after_stop_does_not_advance_or_beep(browser_page):
    page, expect = browser_page
    state = serve_enrollment(page, defer=True)
    start_enrollment(page, expect)
    page.wait_for_function("window.testBeeps.length >= 2")
    assert state["pending"]
    page.locator("#captureFace").click()
    before = page.evaluate("window.testBeeps.length")
    state["pending"][0].fulfill(json={"accepted": True, "completed": False, "captured_poses": ["front"], "pitch": 0})
    page.wait_for_timeout(900)
    expect(page.locator("#poseTitle")).to_have_text("Nhìn thẳng")
    expect(page.locator("#poseMessage")).to_contain_text("Đã tạm dừng")
    assert page.evaluate("window.testBeeps.length") == before


def test_enrollment_error_stops_beeps_without_a_success_tone(browser_page):
    page, expect = browser_page
    serve_enrollment(page, fail=True)
    start_enrollment(page, expect)
    expect(page.locator("#notice")).to_have_text("Lỗi thử nghiệm")
    before = page.evaluate("window.testBeeps.length")
    page.wait_for_timeout(900)
    assert page.evaluate("window.testBeeps.length") == before
    assert not page.evaluate("window.testBeeps.some(b => b.duration > .5)")


def test_leaving_enrollment_cancels_the_next_angle_sound_and_capture(browser_page):
    page, expect = browser_page
    state = serve_enrollment(page, accept=True)
    start_enrollment(page, expect)
    page.wait_for_function("window.testBeeps.some(b => b.duration > .5)")
    expect(page.locator("#poseTitle")).to_have_text("Quay sang trái")
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    before = page.evaluate("window.testBeeps.length")
    page.wait_for_timeout(2300)
    assert page.evaluate("window.testBeeps.length") == before
    assert len(state["scans"]) == 1
    expect(page.locator("#faceStudent")).to_be_enabled()
