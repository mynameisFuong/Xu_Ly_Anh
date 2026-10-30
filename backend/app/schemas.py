from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "teacher"
    full_name: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    full_name: str
    is_active: bool


class StudentCreate(BaseModel):
    student_code: str
    full_name: str
    class_label: str | None = None
    consent_status: str = "pending"


class StudentUpdate(BaseModel):
    student_code: str | None = None
    full_name: str | None = None
    class_label: str | None = None
    consent_status: str | None = None


class StudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_code: str
    full_name: str
    class_label: str | None
    consent_status: str


class StudentImportRow(BaseModel):
    row_number: int
    student_code: str
    full_name: str
    class_label: str | None
    consent_status: str
    status: str
    message: str


class StudentImportResult(BaseModel):
    dry_run: bool
    digest: str
    total: int
    valid: int
    imported: int
    skipped: int
    failed: int
    rows: list[StudentImportRow]


class StudentFaceSummary(BaseModel):
    id: int
    student_code: str
    full_name: str
    class_label: str | None
    class_codes: list[str] = Field(default_factory=list)
    consent_status: str
    face_template_count: int
    captured_pose_count: int = 0
    enrollment_complete: bool = False
    face_status: str = "incomplete"
    latest_image_path: str | None
    latest_image_url: str | None


class ClassCreate(BaseModel):
    code: str
    name: str
    teacher_id: int
    term: str | None = None


class ClassRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    teacher_id: int
    teacher_display_name: str | None = None
    term: str | None


class SessionCreate(BaseModel):
    start_time: datetime | None = None
    expected_start_time: datetime | None = None
    planned_end_time: datetime | None = None
    late_grace_minutes: int = Field(default=0, ge=0, le=180)

    _utc_times = field_validator("start_time", "expected_start_time", "planned_end_time")(utc_datetime)


class SessionPolicyUpdate(BaseModel):
    expected_start_time: datetime
    late_grace_minutes: int = Field(default=0, ge=0, le=180)

    _utc_times = field_validator("expected_start_time")(utc_datetime)


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_id: int
    opened_by: int
    start_time: datetime
    expected_start_time: datetime | None
    planned_end_time: datetime | None
    late_grace_minutes: int
    end_time: datetime | None
    status: str

    _utc_times = field_validator("start_time", "expected_start_time", "planned_end_time", "end_time")(utc_datetime)


class AttendanceRequestStudent(BaseModel):
    student_code: str
    full_name: str
    class_label: str | None = None


class AttendanceRequestCreate(BaseModel):
    class_code: str
    class_name: str
    teacher_name: str
    students: list[AttendanceRequestStudent]
    expected_start_time: datetime
    planned_end_time: datetime
    late_grace_minutes: int = Field(default=0, ge=0, le=180)

    _utc_times = field_validator("expected_start_time", "planned_end_time")(utc_datetime)


class AttendanceRequestRead(BaseModel):
    session_id: int
    class_id: int
    class_code: str
    class_name: str
    teacher_name: str | None
    expected_start_time: datetime | None
    planned_end_time: datetime | None
    late_grace_minutes: int
    status: str
    student_count: int

    _utc_times = field_validator("expected_start_time", "planned_end_time")(utc_datetime)


class RecognitionEventCreate(BaseModel):
    camera_id: str = "camera-0"
    student_id: int | None = None
    candidate_score: float | None = Field(default=None, ge=0.0, le=1.0)
    second_score: float | None = Field(default=None, ge=0.0, le=1.0)
    decision: str
    frame_time: datetime | None = None
    model_version: str
    idempotency_key: str

    _utc_times = field_validator("frame_time")(utc_datetime)


class RecognitionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    camera_id: str
    student_id: int | None
    candidate_score: float | None
    decision: str
    created_at: datetime

    _utc_times = field_validator("created_at")(utc_datetime)


class AttendanceManualUpdate(BaseModel):
    status: str
    reason: str


class AttendanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    student_id: int
    status: str
    source: str
    recognized_event_id: int | None
    recorded_at: datetime
    late_minutes: int
    evidence_image_path: str | None = None
    evidence_image_url: str | None = None
    updated_by: int | None

    _utc_times = field_validator("recorded_at")(utc_datetime)


class AttendanceBoardRow(BaseModel):
    student_id: int
    student_code: str
    full_name: str
    class_label: str | None
    status: str
    source: str | None
    recorded_at: datetime | None
    late_minutes: int
    alert: str
    evidence_image_url: str | None = None

    _utc_times = field_validator("recorded_at")(utc_datetime)


class AttendanceBoardRead(BaseModel):
    session_id: int
    class_id: int
    expected_start_time: datetime | None
    late_grace_minutes: int
    rows: list[AttendanceBoardRow]

    _utc_times = field_validator("expected_start_time")(utc_datetime)


class AttendanceStatsRead(BaseModel):
    session_id: int
    class_id: int
    total_students: int
    present_count: int
    late_count: int
    absent_count: int
    pending_count: int
    present_rate: float
    late_rate: float
    absent_rate: float


class FrameScanRequest(BaseModel):
    camera_id: str = Field(default="browser-camera", max_length=80)
    image_base64: str = Field(max_length=2_800_000)
    idempotency_key: str | None = Field(default=None, max_length=120)


class FrameScanResponse(BaseModel):
    decision: str
    message: str
    already_recorded: bool = False
    student_id: int | None = None
    student_code: str | None = None
    full_name: str | None = None
    class_label: str | None = None
    class_name: str | None = None
    candidate_score: float | None = None
    second_score: float | None = None
    attendance: AttendanceRead | None = None
    face_box: tuple[int, int, int, int] | None = None


class StreamScanRequest(BaseModel):
    camera_id: str = Field(default="browser-camera", min_length=1, max_length=80)
    stream_id: str = Field(min_length=1, max_length=80)
    frame_id: int = Field(ge=0, le=2_147_483_647)
    image_base64: str = Field(max_length=2_800_000)


class StreamFaceResult(FrameScanResponse):
    track_id: str
    confirmation_hits: int = 0
    confirmation_required: int = 3


class StreamScanResponse(BaseModel):
    frame_id: int
    frame_width: int
    frame_height: int
    faces: list[StreamFaceResult]
    message: str
    processing_ms: float
    timings_ms: dict[str, float] = Field(default_factory=dict)
    next_frame_delay_ms: int = 100


class FaceImportItem(BaseModel):
    filename: str
    student_code: str | None = None
    status: str
    detail: str


class FaceImportResponse(BaseModel):
    imported: int
    failed: int
    items: list[FaceImportItem]


class FaceTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    model_name: str
    model_version: str
    embedding_dim: int
    image_path: str | None
    quality_score: float | None
    pose_label: str | None = None
    is_active: bool


class FaceEnrollmentScanRequest(BaseModel):
    image_base64: str = Field(max_length=2_800_000)
    target_pose: str
    neutral_pitch: float | None = None
    neutral_yaw: float | None = None
    enrollment_id: str | None = Field(default=None, min_length=32, max_length=32)


class FaceEnrollmentProgress(BaseModel):
    accepted: bool
    message: str
    detected_pose: str | None = None
    target_pose: str
    yaw: float | None = None
    pitch: float | None = None
    captured_poses: list[str]
    missing_poses: list[str]
    progress_percent: int
    completed: bool
    engine: str


class DashboardSummaryRead(BaseModel):
    total_students: int
    enrolled_students: int
    active_classes: int
    open_sessions: int
    attendance_today: int
    attendance_rate_today: float


class SessionSummaryRead(BaseModel):
    id: int
    class_id: int
    class_code: str
    class_name: str
    teacher_name: str | None
    start_time: datetime
    expected_start_time: datetime | None
    end_time: datetime | None
    status: str
    total_students: int
    present_count: int
    late_count: int
    absent_count: int
    attendance_rate: float

    _utc_times = field_validator("start_time", "expected_start_time", "end_time")(utc_datetime)
