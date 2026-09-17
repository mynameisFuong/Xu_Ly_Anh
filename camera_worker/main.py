import argparse
import base64
import time
import uuid

import cv2
import numpy as np
import requests

from ai_pipeline.recognition import FaceRecognizer, match_embedding
from ai_pipeline.temporal import TemporalConfirmer
from backend.app.config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-camera attendance worker")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--class-id", type=int, required=True)
    parser.add_argument("--camera-id", default="camera-0")
    parser.add_argument("--token", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_templates(api_base: str, class_id: int, token: str, model_version: str) -> dict[int, list[np.ndarray]]:
    response = requests.get(
        f"{api_base}/classes/{class_id}/face-templates",
        headers={"X-Camera-Token": token},
        timeout=10,
    )
    response.raise_for_status()
    templates: dict[int, list[np.ndarray]] = {}
    for item in response.json():
        if item["model_version"] != model_version:
            continue
        raw = base64.b64decode(item["embedding_base64"])
        embedding = np.frombuffer(raw, dtype=np.float32)
        if embedding.shape[0] != item["embedding_dim"]:
            continue
        templates.setdefault(item["student_id"], []).append(embedding)
    return templates


def post_recognition(api_base: str, token: str, session_id: int, payload: dict) -> None:
    response = requests.post(
        f"{api_base}/sessions/{session_id}/recognition-events",
        json=payload,
        headers={"X-Camera-Token": token},
        timeout=5,
    )
    response.raise_for_status()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    token = args.token or settings.camera_api_token

    recognizer = FaceRecognizer()
    templates = load_templates(args.api, args.class_id, token, recognizer.model_version)
    confirmer = TemporalConfirmer(settings.attendance_min_hits, settings.attendance_window_seconds)

    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open camera {args.camera}")

    print("Camera worker started. Press q to stop.")
    while True:
        ok, frame = capture.read()
        if not ok:
            print("Camera frame read failed; retrying...")
            time.sleep(1)
            continue

        for box, embedding in recognizer.extract_embeddings_from_frame(frame):
            match = match_embedding(
                embedding,
                templates,
                threshold=settings.attendance_threshold,
                margin=settings.attendance_margin,
            )
            x, y, w, h = box
            color = (0, 255, 0) if match.decision == "recognized" else (0, 165, 255)
            label = match.decision
            if match.student_id is not None and confirmer.observe(match.student_id):
                payload = {
                    "camera_id": args.camera_id,
                    "student_id": match.student_id,
                    "candidate_score": match.score,
                    "second_score": match.second_score,
                    "decision": match.decision,
                    "model_version": recognizer.model_version,
                    "idempotency_key": str(uuid.uuid4()),
                }
                label = f"sent:{match.student_id}"
                if not args.dry_run:
                    post_recognition(args.api, token, args.session_id, payload)
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, label, (x, max(y - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.imshow("Face Attendance Camera", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    capture.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
