#!/usr/bin/env python3
"""批量 Stage9 封面：转发到 ``batch_doll_blender_stage9_11.py --pass covers``。

用法: ``python scripts/batch_doll_stage9_covers.py --pipeline 卡通人偶定制``
其余参数与该脚本一致（``--fashion-tag``、``--resume`` 等）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    cmd = [
        sys.executable,
        str(_REPO / "scripts" / "batch_doll_blender_stage9_11.py"),
        "--pass",
        "covers",
        *sys.argv[1:],
    ]
    raise SystemExit(subprocess.call(cmd, cwd=str(_REPO)))


if __name__ == "__main__":
    main()
