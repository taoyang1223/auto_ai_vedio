#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, SRC.as_posix())

from auto_video.comfyui_image_adapter import main


if __name__ == "__main__":
    raise SystemExit(main())
