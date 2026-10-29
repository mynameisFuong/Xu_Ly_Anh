"""Chạy web local từ .env hiện tại, tránh biến cũ do terminal IDE giữ lại."""

import argparse
import os
from pathlib import Path
import sys


def prepare_local_environment(project_root: Path) -> None:
    from dotenv import load_dotenv

    os.chdir(project_root)
    # Chỉ launcher local chọn .env làm nguồn ưu tiên. Uvicorn triển khai trực tiếp
    # vẫn giữ quy tắc environment > dotenv tiêu chuẩn của Pydantic Settings.
    load_dotenv(project_root / ".env", override=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    prepare_local_environment(root)
    import uvicorn

    uvicorn.run("backend.app.main:app", host=args.host, port=args.port, reload=args.reload,
                reload_dirs=[str(root)] if args.reload else None)


if __name__ == "__main__":
    main()
