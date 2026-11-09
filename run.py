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


def main() -> int:
    enable_dpi_awareness()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("当前 Python 没有 tkinter，请改用完整安装的 Python 3.10+ 运行。")
        print(f"解释器：{sys.executable}")
        return 1

    from quizwin.ui.app import App

    try:
        app = App()
    except Exception as exc:  # pragma: no cover - 启动期兜底
        import traceback

        traceback.print_exc()
        try:
            from tkinter import messagebox

            messagebox.showerror("启动失败", f"{exc}\n\n详情见控制台输出。")
        except Exception:
            pass
        return 1

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
