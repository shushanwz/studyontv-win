"""截规则页底部的「家长控制」分区。

页面很长，家长分区在最下面，普通截图截不到。用临时数据目录，
不碰程序目录里的真实状态。

用法： python tools/shot_rules.py [dark|light] [输出文件]
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

TMP = Path(tempfile.mkdtemp(prefix="quizwin-shot-")) / "data"
(TMP / "banks").mkdir(parents=True)
for _file in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(_file, TMP / "banks" / _file.name)
os.environ["QUIZWIN_DATA"] = str(TMP)
os.environ["QUIZWIN_NO_GUARD"] = "1"

from quizwin.core.parent import ParentControl  # noqa: E402
from quizwin.core.storage import Storage, today_key  # noqa: E402


def main(argv: list[str]) -> int:
    from run import enable_dpi_awareness

    enable_dpi_awareness()

    from quizwin.ui.app import App
    from winshot import capture, window_handle

    mode = "light" if "light" in argv else "dark"
    out = Path(argv[-1]) if argv and argv[-1].endswith(".bmp") else ROOT / "shots" / f"_rules-{mode}.bmp"

    storage = Storage()
    control = ParentControl(storage)
    control.set_password("123456")
    storage.state["theme"] = mode
    storage.state["today"] = {"day": today_key(), "credit_ms": 8 * 60_000, "used_ms": 0, "rounds_done": 0}
    storage.save_state()

    app = App()
    app.set_page("rules")
    app.update()
    page = app.pages["rules"]
    page.scroll.canvas.yview_moveto(1.0)
    app.update()
    for _ in range(8):
        app.update()
    out.parent.mkdir(parents=True, exist_ok=True)
    capture(window_handle(app), out)
    print(f"已截图： {out}")
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
