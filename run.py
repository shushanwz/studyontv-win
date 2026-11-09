"""题了个题 · 桌面版 —— 程序入口。

直接运行：
    python run.py
或双击「启动.bat」（会自动挑一个带 tkinter 的 Python）。
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def enable_dpi_awareness() -> None:
    """让高分屏下的界面保持清晰，而不是被系统拉伸模糊。"""
    if sys.platform != "win32":
        return
    try:
        # 2 = Per-Monitor DPI Aware：窗口、字体与系统缩放保持一致，
        # 避免高分屏下界面被系统二次拉伸导致发虚。
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


UNLOCK_FLAG = ROOT / "unlock.flag"


def consume_unlock_flag() -> bool:
    """家长救急通道：程序目录放一个 unlock.flag，本次跳过锁屏，用完即删。"""
    if not UNLOCK_FLAG.exists():
        return False
    try:
        UNLOCK_FLAG.unlink()
    except OSError:
        pass
    return True


def decide_lock_mode(argv: list[str]) -> bool:
    """有密码且启用了家长控制 → 全屏锁屏；否则正常窗口。

    「没设密码就不许锁屏」是硬约束：锁屏的第一道门就是密码，
    密码都没设就锁，等于把家长自己关在外面。
    """
    if "--no-lock" in argv or "--unlock" in argv:
        return False
    if "--force-lock" in argv:
        # 看门狗拉起时用：这里已经确认过「之前就是锁屏态、且密码存在」，
        # 不再重新判断，否则状态文件一时读不出来就漏锁了。
        return True
    if consume_unlock_flag():
        print("已读取 unlock.flag：本次跳过锁屏，文件已删除。")
        return False
    try:
        from quizwin.core.parent import ParentControl
        from quizwin.core.storage import Storage

        control = ParentControl(Storage())
        return bool(control.enabled and control.has_password)
    except Exception:
        # 状态读不出来时不要把人锁在外面
        return False


def main() -> int:
    enable_dpi_awareness()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("当前 Python 没有 tkinter，请改用完整安装的 Python 3.10+ 运行。")
        print(f"解释器：{sys.executable}")
        return 1

    from quizwin.ui.app import App

    lock_mode = decide_lock_mode(sys.argv[1:])
    try:
        app = App(lock_mode=lock_mode)
    except Exception as exc:  # pragma: no cover - 启动期兜底
        import traceback

        traceback.print_exc()
        try:
            from tkinter import messagebox

            messagebox.showerror("启动失败", f"{exc}\n\n详情见控制台输出。")
        except Exception:
            pass
        return 1

    if not lock_mode:
        # 首次运行且没设密码：问一次要不要启用家长控制（放在入口层，测试不受影响）
        app.after(1200, app._maybe_setup_parent)

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
