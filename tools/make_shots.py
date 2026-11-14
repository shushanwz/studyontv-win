"""批量生成展示截图：调用 tools/shot.py 抓 BMP，再转成 PNG 放进 shots/。

用法： python tools/make_shots.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

CASES = [
    ("01-开始页", ["quiz", "--start"]),
    ("02-答题页", ["quiz"]),
    ("03-作答反馈", ["quiz", "--answer"]),
    ("04-结算页", ["quiz", "--result"]),
    ("05-主观题自评", ["quiz", "--type", "subjective", "--answer"]),
    ("06-使用计时", ["quiz", "--watch"]),
    ("07-今日已满", ["quiz", "--blocked"]),
    ("08-题库管理", ["bank"]),
    ("09-题目编辑", ["bank", "--dialog"]),
    ("10-规则设置", ["rules"]),
    ("11-关于页面", ["about"]),
    ("12-浅色主题", ["quiz", "--light"]),
    ("18-最后30秒", ["quiz", "--overlay", "25"]),
]


def main() -> int:
    raw = Path(tempfile.mkdtemp(prefix="quizwin-shots-"))
    out_dir = ROOT / "shots"
    out_dir.mkdir(exist_ok=True)
    from PIL import Image

    for name, args in CASES:
        bmp = raw / f"{name}.bmp"
        print("抓图：", name)
        result = subprocess.run(
            [PY, str(ROOT / "tools" / "shot.py"), args[0], str(bmp), *args[1:]],
            cwd=str(ROOT),
            capture_output=True,
        )
        if not bmp.exists():
            print("  失败：", result.stdout.decode("utf-8", "replace")[-300:], result.stderr.decode("utf-8", "replace")[-300:])
            continue
        target = out_dir / f"{name}.png"
        Image.open(bmp).save(target)
        print("  ->", target.name, f"{target.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
