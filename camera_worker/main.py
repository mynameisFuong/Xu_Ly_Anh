import argparse
import base64
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        try:
            raw = base64.b64decode(item["embedding_base64"], validate=True)
            embedding = np.frombuffer(raw, dtype=np.float32)
        except ValueError:
            continue
        if embedding.shape[0] != item["embedding_dim"] or not np.isfinite(embedding).all():
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


def load_pipeline_policy(api_base: str, token: str) -> dict:
    response = requests.get(f"{api_base}/camera/pipeline", headers={"X-Camera-Token": token}, timeout=10)
    response.raise_for_status()
    policy = response.json()
    if any(policy.get(key) not in {"off", "shadow", "enforce"} for key in ("liveness_mode", "preprocessing_mode")):
        raise RuntimeError("Backend returned an unsupported pipeline policy")
    return policy


def scan_on_server(api_base, token, session_id, camera_id, stream_id, frame, *, dry_run=False):
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        return {"decision": "unknown", "message": "Cannot encode camera frame"}
    response = requests.post(
        f"{api_base}/sessions/{session_id}/camera-scan-frame",
        params={"dry_run": str(dry_run).lower(), "stream_id": stream_id},
        json={"camera_id": camera_id, "image_base64": base64.b64encode(encoded.tobytes()).decode("ascii"),
              "idempotency_key": str(uuid.uuid4())},
        headers={"X-Camera-Token": token}, timeout=15,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    token = args.token or settings.camera_api_token

    policy = load_pipeline_policy(args.api, token)
    server_analysis = policy["liveness_mode"] != "off" or policy["preprocessing_mode"] != "off"
    recognizer = None if server_analysis else FaceRecognizer()
    templates = {} if server_analysis else load_templates(args.api, args.class_id, token, recognizer.model_version)
    confirmer = TemporalConfirmer(settings.attendance_min_hits, settings.attendance_window_seconds)
    stream_id = str(uuid.uuid4())
    last_scan = float("-inf")
    last_server_result = {}

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

        if server_analysis:
            if time.monotonic() - last_scan >= 1.0:
                last_scan = time.monotonic()
                try:
                    last_server_result = scan_on_server(
                        args.api, token, args.session_id, args.camera_id, stream_id, frame, dry_run=args.dry_run,
                    )
                except requests.RequestException:
                    # Never fall back to unverified events after a failed server gate.
                    last_server_result = {"decision": "unknown", "message": "Server analysis unavailable"}
            box = last_server_result.get("face_box")
            if box:
                x, y, w, h = box
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 200, 255), 2)
            cv2.putText(frame, last_server_result.get("decision", "unknown"), (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
            cv2.imshow("Face Attendance Camera", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            continue

        detections = recognizer.extract_embeddings_from_frame(frame)
        if not detections:
            confirmer.reset()
        for box, embedding in detections:
            match = match_embedding(
                embedding,
                templates,
                threshold=(
                    settings.face_distance_threshold
                    if recognizer.distance_metric == "euclidean"
                    else settings.attendance_threshold
                ),
                margin=(
                    settings.face_distance_margin
                    if recognizer.distance_metric == "euclidean"
                    else settings.attendance_margin
                ),
                metric=recognizer.distance_metric,
            )
            x, y, w, h = box
            color = (0, 255, 0) if match.decision == "recognized" else (0, 165, 255)
            label = match.decision
            if match.student_id is None:
                confirmer.reset()
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
