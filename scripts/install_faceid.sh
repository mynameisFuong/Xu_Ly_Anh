#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
project_python="$project_dir/.venv/bin/python"
cd "$project_dir"

if [[ ! -x "$project_python" ]]; then
  echo "Chua co .venv. Hay tao venv va cai requirements.txt, requirements-camera.txt truoc." >&2
  exit 1
fi

"$project_python" -m pip install \
  'dlib-bin==20.0.1.post1' \
  'face-recognition-models==0.3.0' \
  'Pillow>=11' \
  'click>=8' \
  'setuptools<81'
# face-recognition khai bao dependency ten "dlib", con dlib-bin cung cap module dlib.
"$project_python" -m pip install 'face-recognition==1.3.0' --no-deps
"$project_python" -c 'from ai_pipeline.recognition import FaceRecognizer; engine = FaceRecognizer(); assert engine.supports_pose; print("Face ID engine ready:", engine.model_name)'
