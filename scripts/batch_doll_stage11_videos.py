#!/usr/bin/env python3
"""批量 Stage11 视频：转发到 ``batch_doll_blender_stage9_11.py --pass videos``。

默认「整批」并发：未写 ``--theme-workers`` 时最多同时跑 6 个主题；每个主题内 ``--inner-workers``
默认为 1（单 Blender 渲该主题）。需要单主题内多 Blender 时再显式 ``--inner-workers N``。

用法: ``python scripts/batch_doll_stage11_videos.py --pipeline 卡通人偶定制 --studio-tint-hex '#E3D9C6'``
其余参数与该脚本一致（``--theme-workers``、``--inner-workers``、``--resume``、``--all-glbs`` 等）。
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
        "videos",
        *sys.argv[1:],
    ]
    raise SystemExit(subprocess.call(cmd, cwd=str(_REPO)))


if __name__ == "__main__":
    main()
