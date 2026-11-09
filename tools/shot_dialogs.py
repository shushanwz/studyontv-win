"""给家长密码框与首次设置向导截图，方便肉眼复核。

用法（一次只截一张，避免多个模态框互相抢占）：
    python tools/shot_dialogs.py password
    python tools/shot_dialogs.py recovery
    python tools/shot_dialogs.py setup
    python tools/shot_dialogs.py setupcode
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

TMP = Path(tempfile.mkdtemp(prefix="quizwin-dlg-")) / "data"
(TMP / "banks").mkdir(parents=True)
for _file in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(_file, TMP / "banks" / _file.name)
os.environ["QUIZWIN_DATA"] = str(TMP)

from run import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from quizwin.core.parent import ParentControl  # noqa: E402
from quizwin.core.storage import Storage  # noqa: E402
from quizwin.ui.app import App  # noqa: E402
from quizwin.ui.page_lock import ParentSetupDialog, PasswordDialog  # noqa: E402
from winshot import capture, window_handle  # noqa: E402


OUT = ROOT / "shots"
TARGETS = {"password": "64-password.bmp", "recovery": "65-password-recovery.bmp",
           "setup": "66-parent-setup.bmp", "setupcode": "67-parent-recovery.bmp"}


def settle(widget, rounds: int = 16) -> None:
    widget.update_idletasks()
    for _ in range(rounds):
        widget.update()
        time.sleep(0.12)


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "password"
    if which not in TARGETS:
        print("可选：", " / ".join(TARGETS))
        return 1

    control = ParentControl(Storage())
    control.set_password("123456")

    app = App()
    app.update()

    if which in ("password", "recovery"):
        dialog = PasswordDialog(app, app, "家长密码", "输入家长密码后可以解锁电脑或修改设置")
        if which == "recovery":
            dialog._build_recovery_panel()
        settle(dialog)
        OUT.mkdir(parents=True, exist_ok=True)
        capture(window_handle(dialog), OUT / TARGETS[which])
        print(f"已截图： shots/{TARGETS[which]}")
        os._exit(0)

    control.cfg["password"] = {}
    control.cfg["setupDone"] = False
    control.st.save_state()
    setup = ParentSetupDialog(app, app)
    if which == "setupcode":
        setup.pass1.entry.insert(0, "123456")
        setup.pass2.entry.insert(0, "123456")
        setup._save()
    settle(setup)
    OUT.mkdir(parents=True, exist_ok=True)
    capture(window_handle(setup), OUT / TARGETS[which])
    print(f"已截图： shots/{TARGETS[which]}")
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
