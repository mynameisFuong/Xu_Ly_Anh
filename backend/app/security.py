import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models import (AuthSession, AttendanceRecord, Class, ClassEnrollment, ClassSession, DeviceClassAccess,
                                User, UserRole, utc_now)

PASSWORD_ROUNDS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PASSWORD_ROUNDS).hex()
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if "$" not in password_hash:
            return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), password_hash)
        # Local databases may already contain hashes written by the PBKDF2 upgrade.
        algorithm, rounds, salt, digest = password_hash.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


bearer = HTTPBearer(auto_error=False)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(db: Session, user: User) -> dict:
    token = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(hours=get_settings().auth_session_hours)
    db.query(AuthSession).filter(AuthSession.expires_at <= utc_now()).delete(synchronize_session=False)
    db.add(AuthSession(token_hash=token_digest(token), user_id=user.id, expires_at=expires))
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_at": expires.isoformat(),
            "user_id": user.id, "role": user.role, "full_name": user.full_name}


def allowed_class_ids(user: User):
    if user.role == "admin":
        return select(Class.id)
    if user.role == "teacher":
        return select(Class.id).where(Class.teacher_id == user.id)
    return select(DeviceClassAccess.class_id).where(DeviceClassAccess.user_id == user.id)


def check_class_access(db: Session, user: User, class_id: int) -> None:
    if db.scalar(select(Class.id).where(Class.id == class_id, Class.id.in_(allowed_class_ids(user)))) is None:
        raise HTTPException(403, "Bạn chưa được phân công lớp này.")


def _check_resource_access(request: Request, db: Session, user: User) -> None:
    """Apply class ownership to authenticated session/class URLs and report queries."""
    if user.role == "admin":
        return
    params = dict(request.path_params)
    if request.url.path.startswith("/reports/") and "session_id" in request.query_params:
        params["session_id"] = request.query_params["session_id"]
    try:
        class_id = int(params["class_id"]) if "class_id" in params else None
        session_id = int(params["session_id"]) if "session_id" in params else None
        if "attendance_id" in params:
            record = db.get(AttendanceRecord, int(params["attendance_id"]))
            if record is None:
                raise HTTPException(404, "Attendance not found")
            session_id = record.session_id
        if session_id is not None:
            session = db.get(ClassSession, session_id)
            if session is None:
                raise HTTPException(404, "Session not found")
            check_class_access(db, user, session.class_id)
        if class_id is not None:
            check_class_access(db, user, class_id)
        if "student_id" in request.path_params and class_id is None and session_id is None:
            enrolled = db.scalar(select(ClassEnrollment.id).where(
                ClassEnrollment.student_id == int(params["student_id"]),
                ClassEnrollment.class_id.in_(allowed_class_ids(user))))
            if enrolled is None:
                raise HTTPException(403, "Sinh viên không thuộc lớp được phân công.")
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid resource identifier") from exc


def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Vui lòng đăng nhập lại.")
    session = db.get(AuthSession, token_digest(credentials.credentials))
    if session is None or session.expires_at.replace(tzinfo=utc_now().tzinfo) <= utc_now():
        raise HTTPException(status_code=401, detail="Phiên đăng nhập đã hết hạn.")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    _check_resource_access(request, db, user)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def require_teacher_or_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ADMIN.value, UserRole.TEACHER.value}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher/admin role required")
    return user


def require_user_or_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ADMIN.value, UserRole.USER.value, UserRole.TEACHER.value}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User/admin role required")
    return user


def verify_camera_token(x_camera_token: str = Header(...)) -> None:
    expected = get_settings().camera_api_token
    if not hmac.compare_digest(x_camera_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid camera token")
