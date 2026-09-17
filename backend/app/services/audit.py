import json
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import AuditLog


def write_audit(
    db: Session,
    *,
    actor_user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str | int,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before_json=json.dumps(before, ensure_ascii=True) if before is not None else None,
        after_json=json.dumps(after, ensure_ascii=True) if after is not None else None,
    )
    db.add(log)
    return log
