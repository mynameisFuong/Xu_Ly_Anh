"""Tải YuNet từ OpenCV Zoo, kiểm checksum và giữ thông báo giấy phép MIT."""

import argparse
from hashlib import sha256
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_pipeline.detection import YUNET_BASE_URL, YUNET_COMMIT, YUNET_FILENAME, YUNET_SHA256


def download_detector(directory):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / YUNET_FILENAME
    if target.exists():
        if sha256(target.read_bytes()).hexdigest() != YUNET_SHA256:
            raise ValueError("Existing YuNet checksum mismatch; use a new directory")
    else:
        request = Request(YUNET_BASE_URL + YUNET_FILENAME, headers={"User-Agent": "AttendAI-model-installer"})
        with urlopen(request, timeout=30) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000 or sha256(data).hexdigest() != YUNET_SHA256:
            raise ValueError("Downloaded YuNet checksum mismatch")
        temporary = target.with_suffix(".onnx.part")
        temporary.write_bytes(data)
        temporary.replace(target)
    license_path = directory / "LICENSE-YuNet.txt"
    if not license_path.exists():
        url = f"https://raw.githubusercontent.com/opencv/opencv_zoo/{YUNET_COMMIT}/models/face_detection_yunet/LICENSE"
        with urlopen(url, timeout=30) as response:
            license_path.write_bytes(response.read(100_000))
    print(f"Verified: {YUNET_FILENAME}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("storage/face-models"))
    download_detector(parser.parse_args().output)
