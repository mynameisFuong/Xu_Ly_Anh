(() => {
  const page = document.body.dataset.page;
  const $ = (id) => document.getElementById(id);
  const accountKey = "face-attendance-account";
  let account = null;
  try {
    account = JSON.parse(sessionStorage.getItem(accountKey) || "null");
  } catch (_) {}
  if (page !== "login" && !account) {
    location.replace("/demo/login");
    return;
  }
  if (page === "login" && account) {
    location.replace("/demo");
    return;
  }

  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char],
    );
  const labels = {
    overview: "Tổng quan",
    students: "Danh sách sinh viên",
    faces: "Đăng ký Face ID",
    sessions: "Buổi học",
    attendance: "Quét điểm danh",
  };
  const statusLabels = {
    present: "Đúng giờ",
    late: "Đi trễ",
    absent: "Vắng",
    pending: "Chưa điểm danh",
    granted: "Đã đồng ý",
    revoked: "Đã thu hồi",
    open: "Đang mở",
    closed: "Đã đóng",
  };
  const badge = (status) =>
    `<span class="badge ${esc(status)}">${statusLabels[status] || esc(status)}</span>`;
  const datetime = (value) =>
    value
      ? new Date(value).toLocaleString("vi-VN", {
          dateStyle: "short",
          timeStyle: "short",
        })
      : "—";
  const localInput = (value) => {
    if (!value) return "";
    const date = new Date(value);
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  };
  function notify(message, kind = "ok") {
    const el = $("notice");
    if (!el) return;
    el.textContent = message;
    el.className = `notice ${kind}`;
    el.hidden = false;
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function clearNotice() {
    if ($("notice")) $("notice").hidden = true;
  }
  async function api(path, options = {}) {
    const headers = {
      ...(account ? { "X-User-Id": String(account.user_id) } : {}),
      ...options.headers,
    };
    const response = await fetch(path, { ...options, headers });
    if (!response.ok) {
      let detail = `Lỗi ${response.status}`;
      try {
        const body = await response.json();
        detail = body.detail || detail;
      } catch (_) {}
      throw new Error(
        Array.isArray(detail)
          ? detail.map((x) => x.msg).join("; ")
          : String(detail),
      );
    }
    if (response.status === 204) return null;
    return response.json();
  }
  const json = (method, path, body) =>
    api(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  const run =
    (fn) =>
    async (...args) => {
      try {
        clearNotice();
        await fn(...args);
      } catch (error) {
        notify(error.message, "error");
      }
    };
  const emptyRow = (cols, message) =>
    `<tr><td colspan="${cols}" class="empty">${esc(message)}</td></tr>`;

  if (page === "login") {
    $("loginForm").addEventListener(
      "submit",
      run(async (event) => {
        event.preventDefault();
        const username = $("username").value.trim();
        const password = $("password").value;
        const result = await json("POST", "/auth/login-json", {
          username,
          password,
        });
        if (result.role !== "admin")
          throw new Error("Giao diện demo dành cho tài khoản quản trị.");
        sessionStorage.setItem(accountKey, JSON.stringify(result));
        location.assign("/demo");
      }),
    );
    return;
  }

  const navGroups = [
    {
      id: "overview",
      title: "Không gian làm việc",
      items: [["overview", "/demo", "◫"]],
    },
    {
      id: "students",
      title: "Quản lý sinh viên",
      items: [["students", "/demo/students", "♙"]],
    },
    {
      id: "faces",
      title: "Đăng ký khuôn mặt",
      items: [["faces", "/demo/faces", "◎"]],
    },
    {
      id: "attendance",
      title: "Điểm danh",
      items: [
        ["sessions", "/demo/sessions", "▤"],
        ["attendance", "/demo/attendance", "◉"],
      ],
    },
  ];
  const navHtml = navGroups
    .map((group) => {
      const items = group.items
        .map(
          ([key, url, icon]) =>
            `<a class="nav-link ${page === key ? "active" : ""}" ${page === key ? 'aria-current="page"' : ""} href="${url}"><span class="nav-icon" aria-hidden="true">${icon}</span><span>${labels[key]}</span></a>`,
        )
        .join("");
      const current = group.items.some(([key]) => key === page);
      return `<div class="nav-group ${current ? "current" : ""}" role="group" aria-labelledby="nav-group-${group.id}"><h2 class="nav-group-title" id="nav-group-${group.id}">${group.title}</h2>${items}</div>`;
    })
    .join("");
  $("shell").insertAdjacentHTML(
    "afterbegin",
    `<aside class="sidebar" id="sidebar"><a class="brand" href="/demo"><span class="brand-mark">FA</span><span><strong>Face Attendance</strong><small>Hệ thống điểm danh</small></span></a><button class="mobile-menu" id="menuToggle" aria-label="Mở menu" aria-expanded="false" aria-controls="sideNav">☰</button><nav class="side-nav" id="sideNav" aria-label="Điều hướng chính">${navHtml}</nav><div class="side-bottom"><small>Đang đăng nhập</small><strong>${esc(account.full_name)}</strong><button class="logout" id="logout">Đăng xuất</button></div></aside>`,
  );
  $("topbar").className = "topbar";
  $("topbar").innerHTML =
    `<span class="crumb">Face Attendance &nbsp;/&nbsp; <strong>${labels[page]}</strong></span><span class="system-pill">Hệ thống nội bộ</span>`;
  $("logout").addEventListener("click", () => {
    sessionStorage.removeItem(accountKey);
    location.assign("/demo/login");
  });
  $("menuToggle").addEventListener("click", () => {
    const open = $("sidebar").classList.toggle("open");
    $("menuToggle").setAttribute("aria-expanded", String(open));
    $("menuToggle").setAttribute("aria-label", open ? "Đóng menu" : "Mở menu");
  });

  async function getClasses() {
    return api("/classes");
  }
  async function getOpenSessions() {
    return api("/attendance-requests/open");
  }
  async function getFaces() {
    return api("/admin/students/faces");
  }

  async function initOverview() {
    const [students, faces, classes, sessions] = await Promise.all([
      api("/students"),
      getFaces(),
      getClasses(),
      getOpenSessions(),
    ]);
    $("mStudents").textContent = students.length;
    $("mFaces").textContent = faces.filter(
      (item) => item.enrollment_complete,
    ).length;
    $("mClasses").textContent = classes.length;
    $("mSessions").textContent = sessions.length;
    $("openSessions").innerHTML = sessions.length
      ? sessions
          .slice(0, 6)
          .map(
            (item) =>
              `<tr><td class="name-cell"><strong>${esc(item.class_code)}</strong><small>${esc(item.class_name)}</small></td><td>${esc(item.teacher_name || "—")}</td><td class="mono">${datetime(item.expected_start_time)}</td><td>${item.student_count}</td><td><a class="btn secondary small" href="/demo/attendance?session=${item.session_id}">Điểm danh →</a></td></tr>`,
          )
          .join("")
      : emptyRow(5, "Chưa có buổi điểm danh đang mở.");
  }

  let students = [],
    classes = [];
  function resetStudentForm() {
    $("studentForm").reset();
    $("editingId").value = "";
    $("formTitle").textContent = "Thêm sinh viên";
    $("consent").value = "pending";
  }
  function renderStudents() {
    const query = $("studentSearch").value.trim().toLocaleLowerCase("vi-VN");
    const consent = $("studentFilter").value;
    const filtered = students.filter(
      (item) =>
        (!consent || item.consent_status === consent) &&
        `${item.student_code} ${item.full_name}`
          .toLocaleLowerCase("vi-VN")
          .includes(query),
    );
    $("studentCount").textContent =
      `${filtered.length} / ${students.length} sinh viên`;
    $("studentsTable").innerHTML = filtered.length
      ? filtered
          .map(
            (item) =>
              `<tr><td class="name-cell"><strong>${esc(item.student_code)}</strong><small>${esc(item.full_name)}</small></td><td>${esc(item.class_label || "—")}</td><td>${badge(item.consent_status)}</td><td>${item.captured_pose_count}/5 góc</td><td><button class="btn secondary small" data-edit="${item.id}">Sửa</button> <a class="btn secondary small" href="/demo/faces?student=${item.id}">Quét Face ID</a> <button class="btn danger small" data-delete="${item.id}">Xóa</button></td></tr>`,
          )
          .join("")
      : emptyRow(5, "Không tìm thấy sinh viên phù hợp.");
  }
  async function reloadStudents() {
    students = await getFaces();
    renderStudents();
  }
  async function initStudents() {
    classes = await getClasses();
    $("enrollClass").innerHTML =
      '<option value="">Chưa chọn lớp</option>' +
      classes
        .map(
          (item) =>
            `<option value="${item.id}">${esc(item.code)} · ${esc(item.name)}</option>`,
        )
        .join("");
    await reloadStudents();
    $("studentSearch").addEventListener("input", renderStudents);
    $("studentFilter").addEventListener("change", renderStudents);
    $("newStudent").addEventListener("click", () => {
      resetStudentForm();
      $("studentCode").focus();
    });
    $("resetStudent").addEventListener("click", resetStudentForm);
    $("studentsTable").addEventListener(
      "click",
      run(async (event) => {
        const edit = event.target.closest("[data-edit]");
        const del = event.target.closest("[data-delete]");
        if (edit) {
          const item = students.find((x) => x.id === Number(edit.dataset.edit));
          if (!item) return;
          $("editingId").value = item.id;
          $("studentCode").value = item.student_code;
          $("fullName").value = item.full_name;
          $("classLabel").value = item.class_label || "";
          $("consent").value = item.consent_status;
          $("enrollClass").value = "";
          $("formTitle").textContent = "Chỉnh sửa sinh viên";
          $("studentForm").scrollIntoView({
            behavior: "smooth",
            block: "center",
          });
          $("studentCode").focus();
        }
        if (del) {
          const item = students.find(
            (x) => x.id === Number(del.dataset.delete),
          );
          if (!item) return;
          if (
            !confirm(
              `Xóa ${item.student_code} · ${item.full_name}? Mẫu khuôn mặt của sinh viên cũng sẽ bị vô hiệu hóa.`,
            )
          )
            return;
          await api(`/students/${item.id}`, { method: "DELETE" });
          resetStudentForm();
          await reloadStudents();
          notify("Đã xóa sinh viên.");
        }
      }),
    );
    $("studentForm").addEventListener(
      "submit",
      run(async (event) => {
        event.preventDefault();
        const id = $("editingId").value;
        const payload = {
          student_code: $("studentCode").value.trim(),
          full_name: $("fullName").value.trim(),
          class_label: $("classLabel").value.trim() || null,
          consent_status: $("consent").value,
        };
        if (!payload.student_code || !payload.full_name)
          throw new Error("Cần nhập MSSV và họ tên.");
        const item = await json(
          id ? "PATCH" : "POST",
          id ? `/students/${id}` : "/students",
          payload,
        );
        if ($("enrollClass").value)
          await api(
            `/classes/${$("enrollClass").value}/enrollments/${item.id}`,
            { method: "POST" },
          );
        resetStudentForm();
        await reloadStudents();
        notify(`Đã lưu sinh viên ${item.student_code}.`);
      }),
    );
  }

  let faceStudents = [],
    faceStream = null,
    faceUrl = null;
  const poses = [
    { id: "front", title: "Nhìn thẳng", hint: "Nhìn vào camera và giữ yên." },
    {
      id: "left",
      title: "Quay sang trái",
      hint: "Quay đầu sang trái và giữ yên.",
    },
    {
      id: "right",
      title: "Quay sang phải",
      hint: "Quay đầu sang phải và giữ yên.",
    },
    { id: "up", title: "Ngẩng lên", hint: "Hơi ngẩng cằm và giữ yên." },
    { id: "down", title: "Cúi xuống", hint: "Hơi cúi cằm và giữ yên." },
  ];
  let enrollStudentId = null;
  let enrollIndex = 0;
  let enrollTimer = null;
  let enrollBusy = false;
  let neutralPitch = null;
  function renderEnrollment(message) {
    $("enrollProgress").hidden = false;
    $("poseList").innerHTML = poses
      .map(
        (pose, index) =>
          `<span class="pose-step ${index < enrollIndex ? "done" : index === enrollIndex ? "active" : ""}" title="${pose.title}" aria-label="${pose.title}: ${index < enrollIndex ? "đã quét" : index === enrollIndex ? "đang quét" : "chưa quét"}">${index < enrollIndex ? "✓" : index + 1}</span>`,
      )
      .join("");
    $("progressBar").style.width = `${Math.min(enrollIndex, 5) * 20}%`;
    const current = poses[enrollIndex];
    const title = current?.title || "Đăng ký hoàn tất";
    const feedback =
      message || (enrollIndex >= 5 ? "Đã ghi nhận đủ năm góc." : current.hint);
    $("poseTitle").textContent = title;
    $("poseMessage").textContent = feedback;
    $("cameraStep").textContent =
      enrollIndex >= 5 ? "Hoàn tất" : `Góc ${enrollIndex + 1} / 5`;
    $("cameraDirection").textContent = title;
    $("cameraFeedback").textContent = feedback;
    $("faceGuideArrow").textContent =
      { front: "●", left: "←", right: "→", up: "↑", down: "↓" }[current?.id] ||
      "✓";
    $("enrollmentCamera").dataset.pose = current?.id || "complete";
    $("enrollmentCamera").classList.toggle(
      "is-scanning",
      Boolean(enrollStudentId) && enrollIndex < 5,
    );
  }
  function stopEnrollment() {
    if (enrollTimer) clearInterval(enrollTimer);
    enrollTimer = null;
    enrollStudentId = null;
    neutralPitch = null;
    $("captureFace").textContent = "Bắt đầu quét 5 góc";
    $("faceStudent").disabled = false;
    $("enrollmentCamera").classList.remove("is-scanning");
  }
  async function scanEnrollment() {
    if (enrollBusy || !enrollStudentId || enrollIndex >= 5) return;
    enrollBusy = true;
    try {
      const video = $("faceVideo"),
        canvas = $("faceCanvas");
      if (!video.videoWidth) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas
        .getContext("2d")
        .drawImage(video, 0, 0, canvas.width, canvas.height);
      const result = await json(
        "POST",
        `/students/${enrollStudentId}/face-enrollment/scan`,
        {
          image_base64: canvas.toDataURL("image/jpeg", 0.88),
          target_pose: poses[enrollIndex].id,
          neutral_pitch: neutralPitch,
        },
      );
      if (result.accepted) {
        if (poses[enrollIndex].id === "front" && Number.isFinite(result.pitch))
          neutralPitch = result.pitch;
        enrollIndex = result.captured_poses.length;
        renderEnrollment(
          result.completed ? "Face ID đã sẵn sàng để điểm danh." : null,
        );
        if (result.completed) {
          stopEnrollment();
          await reloadFaces();
          notify("Đã hoàn tất đăng ký Face ID 5 góc.");
        }
      } else {
        const current = poses[enrollIndex];
        const relativePitch = result.pitch - (neutralPitch ?? 0);
        const needsMoreTilt =
          current.id === "up" &&
          result.detected_pose === "front" &&
          result.message.startsWith("Đang thấy góc") &&
          Number.isFinite(relativePitch);
        renderEnrollment(
          needsMoreTilt
            ? "Ngẩng cằm thêm một chút, mắt vẫn nhìn vào camera và giữ yên."
            : result.message,
        );
      }
    } catch (error) {
      stopEnrollment();
      notify(error.message, "error");
    } finally {
      enrollBusy = false;
    }
  }
  function renderFaces() {
    const query = $("faceSearch").value.trim().toLocaleLowerCase("vi-VN");
    const items = faceStudents.filter((item) =>
      `${item.student_code} ${item.full_name}`
        .toLocaleLowerCase("vi-VN")
        .includes(query),
    );
    $("faceCount").textContent =
      `${faceStudents.filter((x) => x.enrollment_complete).length} / ${faceStudents.length} sinh viên hoàn tất Face ID`;
    $("facesTable").innerHTML = items.length
      ? items
          .map(
            (item) =>
              `<tr><td class="name-cell"><strong>${esc(item.student_code)}</strong><small>${esc(item.full_name)}</small></td><td>${esc(item.class_label || "—")}</td><td>${badge(item.consent_status)}</td><td>${item.enrollment_complete ? '<span class="badge present">Hoàn tất</span>' : `${item.captured_pose_count}/5 góc`}</td><td>${item.latest_image_url ? `<button class="btn secondary small" data-preview="${item.id}">Xem ảnh</button>` : '<span class="muted">Chưa có ảnh</span>'}</td></tr>`,
          )
          .join("")
      : emptyRow(5, "Không tìm thấy sinh viên phù hợp.");
  }
  async function reloadFaces() {
    const selected = $("faceStudent").value;
    faceStudents = await getFaces();
    $("faceStudent").innerHTML =
      '<option value="">Chọn sinh viên</option>' +
      faceStudents
        .filter((x) => x.consent_status === "granted")
        .map(
          (x) =>
            `<option value="${x.id}">${esc(x.student_code)} · ${esc(x.full_name)}</option>`,
        )
        .join("");
    $("faceStudent").value = selected;
    renderFaces();
  }
  async function openCamera(videoId) {
    if (!navigator.mediaDevices?.getUserMedia)
      throw new Error(
        "Trình duyệt không hỗ trợ camera hoặc trang không được mở từ localhost/HTTPS.",
      );
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: "user" },
      audio: false,
    });
    $(videoId).srcObject = stream;
    await $(videoId).play();
    return stream;
  }
  function frameBlob(video, canvas) {
    if (!video.videoWidth) throw new Error("Camera chưa sẵn sàng.");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.88));
  }
  async function initFaces() {
    const classList = await getClasses();
    $("faceClass").innerHTML =
      '<option value="">Chọn lớp học</option>' +
      classList
        .map(
          (x) =>
            `<option value="${x.id}">${esc(x.code)} · ${esc(x.name)}</option>`,
        )
        .join("");
    await reloadFaces();
    const requestedStudent = new URLSearchParams(location.search).get(
      "student",
    );
    if (requestedStudent) $("faceStudent").value = requestedStudent;
    $("faceSearch").addEventListener("input", renderFaces);
    $("faceCamera").addEventListener(
      "click",
      run(async () => {
        if (!faceStream) faceStream = await openCamera("faceVideo");
        notify("Camera đã bật.");
      }),
    );
    $("captureFace").addEventListener(
      "click",
      run(async () => {
        if (enrollTimer) {
          stopEnrollment();
          renderEnrollment("Đã tạm dừng. Bắt đầu lại sẽ xóa các góc vừa quét.");
          return;
        }
        const id = $("faceStudent").value;
        if (!id) throw new Error("Chọn sinh viên đã đồng ý trước khi quét.");
        const student = faceStudents.find((item) => item.id === Number(id));
        const engine = await api("/face-enrollment/engine");
        if (!engine.available)
          throw new Error(
            "Chưa cài engine Face ID đa góc. Xem hướng dẫn cài đặt trong README.",
          );
        if (!faceStream) faceStream = await openCamera("faceVideo");
        if (
          student?.face_template_count &&
          !confirm("Quét lại sẽ vô hiệu hóa các mẫu khuôn mặt cũ. Tiếp tục?")
        )
          return;
        await api(`/students/${id}/face-enrollment/reset`, { method: "POST" });
        enrollStudentId = id;
        enrollIndex = 0;
        neutralPitch = null;
        $("faceStudent").disabled = true;
        $("captureFace").textContent = "Dừng quét";
        renderEnrollment();
        enrollTimer = setInterval(scanEnrollment, 1000);
        scanEnrollment();
      }),
    );
    $("importFaces").addEventListener(
      "click",
      run(async () => {
        const classId = $("faceClass").value;
        if (!classId) throw new Error("Chọn lớp học trước khi nhập ảnh.");
        if (!$("importConsent").checked)
          throw new Error("Cần xác nhận sự đồng ý trước khi nhập ảnh.");
        const selected = [...$("faceFiles").files];
        const files = selected.filter((x) =>
          /\.(jpe?g|png|webp|bmp)$/i.test(x.name),
        );
        if (!files.length) throw new Error("Chọn thư mục có ảnh hợp lệ.");
        const form = new FormData();
        files.forEach((file) => form.append("files", file, file.name));
        const result = await api(
          `/admin/face-import?class_id=${encodeURIComponent(classId)}`,
          { method: "POST", body: form },
        );
        $("importSummary").hidden = false;
        $("importSummary").textContent =
          `Đã nhập ${result.imported} ảnh; ${result.failed} lỗi. ${result.items
            .filter((x) => x.status === "failed")
            .slice(0, 3)
            .map((x) => `${x.filename}: ${x.detail}`)
            .join(" · ")}`;
        await reloadFaces();
        notify(
          `Hoàn tất nhập ảnh: ${result.imported} thành công, ${result.failed} lỗi.`,
          result.failed ? "warn" : "ok",
        );
      }),
    );
    $("facesTable").addEventListener(
      "click",
      run(async (event) => {
        const button = event.target.closest("[data-preview]");
        if (!button) return;
        const item = faceStudents.find(
          (x) => x.id === Number(button.dataset.preview),
        );
        if (!item?.latest_image_url) return;
        const response = await fetch(item.latest_image_url, {
          headers: { "X-User-Id": String(account.user_id) },
        });
        if (!response.ok) throw new Error("Không tải được ảnh.");
        if (faceUrl) URL.revokeObjectURL(faceUrl);
        faceUrl = URL.createObjectURL(await response.blob());
        $("facePreview").innerHTML =
          `<img alt="Ảnh sinh viên"><strong>${esc(item.student_code)} · ${esc(item.full_name)}</strong>`;
        $("facePreview").querySelector("img").src = faceUrl;
      }),
    );
    window.addEventListener("pagehide", () => {
      stopEnrollment();
      faceStream?.getTracks().forEach((track) => track.stop());
      if (faceUrl) URL.revokeObjectURL(faceUrl);
    });
  }

  function sessionRow(item, isOverview = false) {
    return `<tr><td class="mono">#${item.session_id}</td><td class="name-cell"><strong>${esc(item.class_code)}</strong><small>${esc(item.class_name)}</small></td><td class="mono">${datetime(item.expected_start_time)}</td><td>${item.late_grace_minutes} phút</td><td>${item.student_count}</td><td><a class="btn secondary small" href="/demo/attendance?session=${item.session_id}">Điểm danh →</a></td></tr>`;
  }
  async function reloadSessions() {
    const items = await getOpenSessions();
    $("sessionsTable").innerHTML = items.length
      ? items.map((x) => sessionRow(x)).join("")
      : emptyRow(6, "Chưa có buổi đang mở.");
  }
  async function initSessions() {
    const classList = await getClasses();
    $("sessionClass").innerHTML =
      '<option value="">Chọn lớp học</option>' +
      classList
        .map(
          (x) =>
            `<option value="${x.id}">${esc(x.code)} · ${esc(x.name)}</option>`,
        )
        .join("");
    const setDefault = () => {
      const date = new Date();
      date.setHours($("period").value === "morning" ? 7 : 13, 0, 0, 0);
      $("expectedStart").value = localInput(date);
    };
    $("period").addEventListener("change", setDefault);
    setDefault();
    await reloadSessions();
    $("refreshSessions").addEventListener("click", run(reloadSessions));
    $("sessionForm").addEventListener(
      "submit",
      run(async (event) => {
        event.preventDefault();
        const classId = $("sessionClass").value;
        if (!classId) throw new Error("Chọn lớp học.");
        const start = new Date($("expectedStart").value);
        if (Number.isNaN(start.getTime()))
          throw new Error("Giờ vào học không hợp lệ.");
        const result = await json("POST", `/classes/${classId}/sessions`, {
          expected_start_time: start.toISOString(),
          late_grace_minutes: Number($("grace").value),
        });
        location.assign(`/demo/attendance?session=${result.id}`);
      }),
    );
  }

  let scanStream = null,
    scanTimer = null,
    scanBusy = false,
    activeSession = null,
    latestBoard = null,
    lastScanResult = null;
  function renderScanFace(result) {
    const box = $("scanFaceBox");
    const video = $("scanVideo");
    const camera = $("attendanceCamera");
    const face = result?.face_box;
    if (
      !scanTimer ||
      !Array.isArray(face) ||
      face.length !== 4 ||
      !video.videoWidth
    ) {
      box.hidden = true;
      return;
    }
    const [x, y, width, height] = face.map(Number);
    if (
      ![x, y, width, height].every(Number.isFinite) ||
      width <= 0 ||
      height <= 0
    ) {
      box.hidden = true;
      return;
    }
    const scale = Math.max(
      camera.clientWidth / video.videoWidth,
      camera.clientHeight / video.videoHeight,
    );
    const offsetX = (camera.clientWidth - video.videoWidth * scale) / 2;
    const offsetY = (camera.clientHeight - video.videoHeight * scale) / 2;
    // The displayed selfie video is mirrored, while the frame sent to the
    // recognizer is not. Reflect the detected rectangle only for the overlay.
    const left = camera.clientWidth - (offsetX + (x + width) * scale);
    const top = offsetY + y * scale;
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
    box.style.width = `${width * scale}px`;
    box.style.height = `${height * scale}px`;
    const recognized =
      result.decision === "recognized" &&
      result.full_name &&
      result.student_code;
    box.classList.toggle("recognized", Boolean(recognized));
    box.classList.toggle(
      "label-above",
      top + height * scale + 70 > camera.clientHeight,
    );
    $("scanFaceLabel").hidden = !recognized;
    $("scanFaceName").textContent = recognized ? result.full_name : "";
    $("scanFaceCode").textContent = recognized ? result.student_code : "";
    box.hidden = false;
  }
  function stopScan() {
    if (scanTimer) clearInterval(scanTimer);
    scanTimer = null;
    lastScanResult = null;
    if ($("scanFaceBox")) $("scanFaceBox").hidden = true;
    if ($("scanToggle")) $("scanToggle").textContent = "Bắt đầu quét";
    if ($("scanBadge")) {
      $("scanBadge").textContent = "Đã dừng";
      $("scanBadge").className = "badge pending";
    }
  }
  function renderBoard(board) {
    latestBoard = board;
    const rows = board.rows;
    for (const [key, status] of [
      ["countPresent", "present"],
      ["countLate", "late"],
      ["countPending", "pending"],
      ["countAbsent", "absent"],
    ])
      $(key).textContent = rows.filter((x) => x.status === status).length;
    $("attendanceTable").innerHTML = rows.length
      ? rows
          .map(
            (row) =>
              `<tr><td class="name-cell"><strong>${esc(row.student_code)}</strong><small>${esc(row.full_name)}</small></td><td>${esc(row.class_label || "—")}</td><td class="mono">${datetime(row.recorded_at)}</td><td>${badge(row.status)}</td><td>${esc(row.alert || "—")}</td><td><button class="btn secondary small" data-manual="${row.student_id}">Điều chỉnh</button></td></tr>`,
          )
          .join("")
      : emptyRow(6, "Lớp chưa có sinh viên được ghi danh.");
  }
  async function refreshBoard() {
    if (!activeSession) return;
    const board = await api(
      `/sessions/${activeSession.session_id}/attendance-board`,
    );
    renderBoard(board);
  }
  async function chooseSession(id) {
    stopScan();
    const items = await getOpenSessions();
    activeSession = items.find((x) => x.session_id === Number(id)) || null;
    if (!activeSession) {
      $("attendanceTable").innerHTML = emptyRow(
        6,
        "Chọn buổi đang mở để xem danh sách.",
      );
      return;
    }
    sessionStorage.setItem("face-attendance-session", String(id));
    $("activeSession").value = String(id);
    $("policyStart").value = localInput(activeSession.expected_start_time);
    $("policyGrace").value = activeSession.late_grace_minutes;
    $("sessionSubtitle").textContent =
      `${activeSession.class_code} · ${activeSession.class_name}`;
    await refreshBoard();
    history.replaceState(null, "", `/demo/attendance?session=${id}`);
  }
  async function scanOnce() {
    if (scanBusy || !activeSession || !scanStream) return;
    scanBusy = true;
    const sessionId = activeSession.session_id;
    try {
      const blob = await frameBlob($("scanVideo"), $("scanCanvas"));
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
      const result = await json("POST", `/sessions/${sessionId}/scan-frame`, {
        camera_id: "browser-camera",
        image_base64: base64,
        idempotency_key: crypto.randomUUID(),
      });
      if (!scanTimer || activeSession?.session_id !== sessionId) return;
      lastScanResult = result;
      renderScanFace(result);
      const message =
        result.decision === "recognized"
          ? `${result.student_code} · ${result.full_name}: ${result.message}`
          : result.message;
      const log = $("scanLog");
      if (log.querySelector(".muted")) log.innerHTML = "";
      log.insertAdjacentHTML(
        "afterbegin",
        `<li>${esc(message)}<time>${new Date().toLocaleTimeString("vi-VN")}</time></li>`,
      );
      while (log.children.length > 8) log.lastElementChild.remove();
      if (result.decision === "recognized") await refreshBoard();
    } catch (error) {
      stopScan();
      notify(error.message, "error");
    } finally {
      scanBusy = false;
    }
  }
  async function initAttendance() {
    window.addEventListener("resize", () => {
      if (lastScanResult) renderScanFace(lastScanResult);
    });
    const items = await getOpenSessions();
    $("activeSession").innerHTML =
      '<option value="">Chọn buổi điểm danh</option>' +
      items
        .map(
          (x) =>
            `<option value="${x.session_id}">#${x.session_id} · ${esc(x.class_code)} · ${esc(x.class_name)}</option>`,
        )
        .join("");
    const query =
      new URLSearchParams(location.search).get("session") ||
      sessionStorage.getItem("face-attendance-session");
    if (query && items.some((x) => x.session_id === Number(query)))
      await chooseSession(query);
    $("activeSession").addEventListener(
      "change",
      run(async () => {
        if ($("activeSession").value)
          await chooseSession($("activeSession").value);
        else {
          activeSession = null;
          stopScan();
          $("attendanceTable").innerHTML = emptyRow(
            6,
            "Chọn buổi đang mở để xem danh sách.",
          );
        }
      }),
    );
    $("savePolicy").addEventListener(
      "click",
      run(async () => {
        if (!activeSession) throw new Error("Chọn buổi điểm danh.");
        const start = new Date($("policyStart").value);
        if (Number.isNaN(start.getTime()))
          throw new Error("Giờ vào học không hợp lệ.");
        await json("PUT", `/sessions/${activeSession.session_id}/policy`, {
          expected_start_time: start.toISOString(),
          late_grace_minutes: Number($("policyGrace").value),
        });
        activeSession.expected_start_time = start.toISOString();
        activeSession.late_grace_minutes = Number($("policyGrace").value);
        await refreshBoard();
        notify("Đã cập nhật quy định giờ vào học.");
      }),
    );
    $("closeSession").addEventListener(
      "click",
      run(async () => {
        if (!activeSession) throw new Error("Chọn buổi điểm danh.");
        if (
          !confirm(
            `Đóng buổi #${activeSession.session_id}? Sinh viên chưa điểm danh sẽ được ghi vắng.`,
          )
        )
          return;
        stopScan();
        await api(`/sessions/${activeSession.session_id}/close`, {
          method: "POST",
        });
        sessionStorage.removeItem("face-attendance-session");
        location.assign("/demo/sessions");
      }),
    );
    $("scanCamera").addEventListener(
      "click",
      run(async () => {
        if (!scanStream) scanStream = await openCamera("scanVideo");
        notify("Camera đã bật.");
      }),
    );
    $("scanToggle").addEventListener(
      "click",
      run(async () => {
        if (scanTimer) {
          stopScan();
          return;
        }
        if (!activeSession)
          throw new Error("Chọn buổi điểm danh trước khi quét.");
        if (!scanStream) scanStream = await openCamera("scanVideo");
        scanTimer = setInterval(scanOnce, 1600);
        scanOnce();
        $("scanToggle").textContent = "Dừng quét";
        $("scanBadge").textContent = "Đang quét";
        $("scanBadge").className = "badge open";
      }),
    );
    $("refreshBoard").addEventListener("click", run(refreshBoard));
    $("exportCsv").addEventListener(
      "click",
      run(async () => {
        if (!activeSession) throw new Error("Chọn buổi điểm danh.");
        const path = `/reports/attendance.csv?session_id=${activeSession.session_id}`;
        const response = await fetch(path, {
          headers: { "X-User-Id": String(account.user_id) },
        });
        if (!response.ok) throw new Error("Không xuất được báo cáo.");
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = `attendance-${activeSession.session_id}.csv`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }),
    );
    $("attendanceTable").addEventListener(
      "click",
      run(async (event) => {
        const button = event.target.closest("[data-manual]");
        if (!button || !activeSession) return;
        const student = latestBoard?.rows.find(
          (x) => x.student_id === Number(button.dataset.manual),
        );
        if (!student) return;
        $("manualStudent").textContent =
          `${student.student_code} · ${student.full_name}`;
        $("manualStudentId").value = student.student_id;
        $("manualStatus").value =
          student.status === "pending" ? "present" : student.status;
        $("manualReason").value = "";
        $("manualDialog").showModal();
      }),
    );
    $("manualForm").addEventListener(
      "submit",
      run(async (event) => {
        event.preventDefault();
        const reason = $("manualReason").value.trim();
        if (!reason) throw new Error("Nhập lý do điều chỉnh.");
        await json(
          "PUT",
          `/sessions/${activeSession.session_id}/attendance/${$("manualStudentId").value}`,
          { status: $("manualStatus").value, reason },
        );
        $("manualDialog").close();
        await refreshBoard();
        notify("Đã cập nhật điểm danh thủ công.");
      }),
    );
    window.addEventListener("pagehide", () => {
      stopScan();
      scanStream?.getTracks().forEach((track) => track.stop());
    });
  }

  run(async () => {
    if (page === "overview") await initOverview();
    if (page === "students") await initStudents();
    if (page === "faces") await initFaces();
    if (page === "sessions") await initSessions();
    if (page === "attendance") await initAttendance();
  })();
})();
