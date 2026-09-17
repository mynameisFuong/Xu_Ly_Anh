from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "teacher"
    full_name: str


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


class StudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_code: str
    full_name: str
    class_label: str | None
    consent_status: str


class StudentFaceSummary(BaseModel):
    id: int
    student_code: str
    full_name: str
    class_label: str | None
    consent_status: str
    face_template_count: int
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


class SessionPolicyUpdate(BaseModel):
    expected_start_time: datetime
    late_grace_minutes: int = Field(default=0, ge=0, le=180)


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


class RecognitionEventCreate(BaseModel):
    camera_id: str = "camera-0"
    student_id: int | None = None
    candidate_score: float | None = Field(default=None, ge=0.0, le=1.0)
    second_score: float | None = Field(default=None, ge=0.0, le=1.0)
    decision: str
    frame_time: datetime | None = None
    model_version: str
    idempotency_key: str


class RecognitionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    camera_id: str
    student_id: int | None
    candidate_score: float | None
    decision: str
    created_at: datetime


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
    updated_by: int | None


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


class AttendanceBoardRead(BaseModel):
    session_id: int
    class_id: int
    expected_start_time: datetime | None
    late_grace_minutes: int
    rows: list[AttendanceBoardRow]


class FrameScanRequest(BaseModel):
    camera_id: str = "browser-camera"
    image_base64: str
    idempotency_key: str | None = None


class FrameScanResponse(BaseModel):
    decision: str
    message: str
    student_id: int | None = None
    student_code: str | None = None
    full_name: str | None = None
    class_label: str | None = None
    class_name: str | None = None
    candidate_score: float | None = None
    second_score: float | None = None
    attendance: AttendanceRead | None = None


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
    is_active: bool
