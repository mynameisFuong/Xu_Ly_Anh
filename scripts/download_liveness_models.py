"""Tải bộ trọng số ONNX đã ghim checksum; không tự duyệt độ chính xác thực địa."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_pipeline.minifasnet import MODEL_SPECS, MODEL_VERSION, RELEASE_URL


def download_models(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for filename, _scale, checksum in MODEL_SPECS:
        target = directory / filename
        if target.exists():
            if sha256(target.read_bytes()).hexdigest() != checksum:
                raise ValueError(f"Existing artifact checksum mismatch: {filename}; use a new directory")
            continue
        request = Request(RELEASE_URL + filename, headers={"User-Agent": "AttendAI-model-installer"})
        with urlopen(request, timeout=60) as response:
            data = response.read(10_000_001)
        if len(data) > 10_000_000 or sha256(data).hexdigest() != checksum:
            raise ValueError(f"Downloaded artifact checksum mismatch: {filename}")
        temporary = directory / (filename + ".part")
        temporary.write_bytes(data)
        temporary.replace(target)
        print(f"Verified: {filename}")
    manifest = directory / "manifest.json"
    if not manifest.exists():
        manifest.write_text(json.dumps({
            "model_version": MODEL_VERSION,
            "approved_for_enforcement": False,
            "source": "https://github.com/yakhyo/face-anti-spoofing/releases/tag/weights",
            "upstream": "https://github.com/minivision-ai/Silent-Face-Anti-Spoofing",
            "license": "Apache-2.0 (upstream repository; review weight/dataset terms before redistribution)",
            "sha256": {name: digest for name, _, digest in MODEL_SPECS},
        }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("storage/pad-models/minifasnet-v1"))
    args = parser.parse_args()
    download_models(args.output)
    print("Downloaded pretrained models. Field APCER/BPCER have not been evaluated.")
