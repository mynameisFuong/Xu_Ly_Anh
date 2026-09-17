import hashlib
import hmac

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models import User, UserRole


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)


def get_current_user(x_user_id: int = Header(...), db: Session = Depends(get_db)) -> User:
    user = db.get(User, x_user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def require_teacher_or_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ADMIN.value, UserRole.TEACHER.value}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher/admin role required")
    return user


def verify_camera_token(x_camera_token: str = Header(...)) -> None:
    expected = get_settings().camera_api_token
    if not hmac.compare_digest(x_camera_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid camera token")
