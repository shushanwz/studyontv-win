"""题了个题 · 桌面版 —— 程序入口。

源码运行：
    python run.py
双击「启动.bat」也行（会自动挑一个带 tkinter 的 Python）。

打包后同一个入口还承担两个隐藏角色：
    --guard        看门狗守护模式（主进程被杀后把锁屏拉回来）
    --force-lock   被看门狗拉起时直接进锁屏
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def enable_dpi_awareness() -> None:
    """让高分屏下的界面保持清晰，而不是被系统拉伸模糊。"""
    if sys.platform != "win32":
        return
    try:
        # 2 = Per-Monitor DPI Aware：窗口、字体与系统缩放保持一致，
        # 避免高分屏下界面被二次拉伸导致发虚。
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def _say(text: str) -> None:
    """打包成无控制台程序后 stdout 是 None，print 会抛异常。"""
    try:
        if sys.stdout is not None:
            print(text)
    except Exception:
        pass


def _fail(title: str, text: str) -> None:
    """启动失败时把话说清楚——安装版没有控制台，只能用弹窗。"""
    _say(f"{title}: {text}")
    if not FROZEN:
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        pass


def _flag_candidates() -> list[Path]:
    """unlock.flag 的两个落点：程序目录（老用法）与数据目录（一定可写）。"""
    items = [ROOT / "unlock.flag"]
    try:
        from quizwin.core import paths

        items.append(paths.default_data_dir().parent / "unlock.flag")
    except Exception:
        pass
    return items


def consume_unlock_flag() -> bool:
    """家长救急通道：放一个 unlock.flag，本次跳过锁屏，用完即删。"""
    for flag in _flag_candidates():
        if not flag.exists():
            continue
        try:
            flag.unlink()
        except OSError:
            pass
        return True
    return False


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
        _say("已读取 unlock.flag：本次跳过锁屏，文件已删除。")
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
    argv = sys.argv[1:]

    # 守护模式：由主进程以 --guard 拉起，只做「盯着父进程」这一件事
    if "--guard" in argv:
        from quizwin.winapi.watchdog import main as guard_main

        return guard_main(argv)

    enable_dpi_awareness()

    try:
        import tkinter  # noqa: F401
    except ImportError:
        _fail(
            "缺少组件",
            "当前环境没有 tkinter，无法启动图形界面。\n"
            "请改用官方安装包，或安装带 tkinter 的完整 Python 3.10+。",
        )
        return 1

    from quizwin.ui.app import App

    lock_mode = decide_lock_mode(argv)
    try:
        app = App(lock_mode=lock_mode)
    except Exception as exc:  # pragma: no cover - 启动期兜底
        import traceback

        detail = traceback.format_exc()
        _say(detail)
        try:
            from quizwin.core import paths

            log_dir = paths.default_data_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "startup-error.log").write_text(detail, encoding="utf-8")
        except Exception:
            pass
        _fail("启动失败", f"{exc}\n\n详细信息已写入数据目录的 startup-error.log。")
        return 1

    if not lock_mode:
        # 首次运行且没设密码：问一次要不要启用家长控制（放在入口层，测试不受影响）
        app.after(1200, app._maybe_setup_parent)

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
