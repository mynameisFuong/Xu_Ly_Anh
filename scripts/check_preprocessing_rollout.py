"""Read-only profile inventory: never rewrites templates, portraits or .env."""

import argparse
from collections import defaultdict
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v1", "v2", "v3"), default="v2")
    args = parser.parse_args()
    from sqlalchemy import select
    from backend.app.database import SessionLocal
    from backend.app.models import ConsentStatus, FaceTemplate, Student
    from backend.app.services.face_templates import build_default_recognizer, build_preprocessing_options
    from ai_pipeline.recognition import ENROLLMENT_POSES

    recognizer = build_default_recognizer()
    options = replace(build_preprocessing_options(), version=args.version, mode="enforce")
    target = recognizer.model_version.split(":", 1)[0] + ":" + options.profile
    profiles = defaultdict(lambda: defaultdict(set))
    with SessionLocal() as db:
        rows = db.execute(select(FaceTemplate.student_id, FaceTemplate.model_version, FaceTemplate.pose_label)
                          .join(Student).where(FaceTemplate.is_active.is_(True),
                                               Student.consent_status == ConsentStatus.GRANTED.value))
        for student_id, version, pose in rows:
            profiles[version][student_id].add(pose)
    completed = {version: {student_id for student_id, poses in students.items()
                           if set(ENROLLMENT_POSES).issubset(poses)} for version, students in profiles.items()}
    current = completed.get(recognizer.model_version, set())
    ready = completed.get(target, set())
    print(json.dumps({
        "current_model_version": recognizer.model_version, "target_model_version": target,
        "profiles": {version: {"students_with_samples": len(students), "complete_five_poses": len(completed[version])}
                     for version, students in profiles.items()},
        "current_complete_students": len(current), "target_complete_students": len(ready),
        "current_students_missing_target": len(current - ready),
        "ready_to_replace_current_roster": bool(current) and current.issubset(ready),
        "guidance": "Each enrolled student needs five active templates for the selected profile. "
                    "Do not relabel embeddings; re-enroll from camera for a representative evaluation.",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
