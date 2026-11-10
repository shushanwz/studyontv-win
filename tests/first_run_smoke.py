"""首次运行冒烟测试：装好第一次打开就必须是「设置 → 锁屏」，不能是普通窗口。

这一条是 v0.3.1 修的核心问题：老版本新装后打开是个普通窗口，关掉设置向导
之后更永久变成普通窗口，孩子点一下「稍后再说」就彻底绕开了锁屏。

测试全程设 QUIZWIN_NO_GUARD=1，不装键盘钩子、不起看门狗。

运行： python tests/first_run_smoke.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP_ROOT = Path(tempfile.mkdtemp(prefix="quizwin-firstrun-"))
TMP = TMP_ROOT / "data"
(TMP / "banks").mkdir(parents=True)
for _file in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(_file, TMP / "banks" / _file.name)
os.environ["QUIZWIN_DATA"] = str(TMP)
os.environ["QUIZWIN_NO_GUARD"] = "1"

from quizwin.core.parent import ParentControl  # noqa: E402
from quizwin.core.storage import Storage  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def fresh_dir() -> None:
    """把数据目录恢复成「刚装好、什么都没设」的状态。"""
    for item in TMP.glob("*.json"):
        item.unlink()
    for flag in (ROOT / "unlock.flag", TMP.parent / "unlock.flag"):
        if flag.exists():
            flag.unlink()


def test_decide() -> None:
    import run

    print("\n[1] 启动分流：默认就该进锁屏")
    fresh_dir()
    check("没有密码时也进锁屏进程", run.decide_lock_mode([]) is True)
    check("--no-lock 走普通窗口", run.decide_lock_mode(["--no-lock"]) is False)
    check("--unlock 走普通窗口", run.decide_lock_mode(["--unlock"]) is False)
    check("--force-lock 强制锁屏", run.decide_lock_mode(["--force-lock"]) is True)

    flag = TMP.parent / "unlock.flag"
    flag.write_text("1", encoding="utf-8")
    check("unlock.flag 跳过锁屏", run.decide_lock_mode([]) is False)
    check("unlock.flag 用完即删", not flag.exists())

    control = ParentControl(Storage())
    control.set_password("abc123456")
    check("设了密码就进锁屏", run.decide_lock_mode([]) is True)

    control.set_enabled(False)
    check("家长主动停用则普通窗口", run.decide_lock_mode([]) is False)

    control.set_enabled(True)
    check("重新启用后又进锁屏", run.decide_lock_mode([]) is True)


def test_app_first_run() -> None:
    from quizwin.ui.app import App

    print("\n[2] 首次启动：全屏、锁着、等设置")
    fresh_dir()
    app = App(lock_mode=True)
    # 先摘掉延迟弹窗的开关：否则 update() 跑到 120ms 时真的会弹设置页并卡住测试
    required = app.setup_required
    app.setup_required = False
    app.update()
    time.sleep(0.3)
    app.update()

    check("判定需要走首次设置", required is True)
    check("启动即处于锁定", app.lock.is_locked())
    check("窗口全屏无边框", bool(app.overrideredirect()))
    check(
        "窗口尺寸等于屏幕",
        app.winfo_width() >= app.winfo_screenwidth() - 2 and app.winfo_height() >= app.winfo_screenheight() - 2,
        f"{app.winfo_width()}x{app.winfo_height()}",
    )
    check("锁屏形态只有答题页", list(app.pages.keys()) == ["quiz"], str(list(app.pages.keys())))
    check("额度条已挂载", app.lock_bar is not None)
    app.destroy()


def test_setup_dialog() -> None:
    from quizwin.ui.app import App
    from quizwin.ui.page_lock import ParentSetupDialog

    print("\n[3] 设置页：不可跳过，跳过即退出程序")
    fresh_dir()
    app = App(lock_mode=True)
    app.setup_required = False
    app.update()

    dialog = ParentSetupDialog(app, app, fullscreen=True)
    dialog.update()
    check("设置页也是全屏无边框", bool(dialog.overrideredirect()))
    check(
        "设置页铺满屏幕",
        dialog.winfo_width() >= dialog.winfo_screenwidth() - 2,
        f"{dialog.winfo_width()}x{dialog.winfo_height()}",
    )

    texts: list[str] = []

    def walk(widget) -> None:
        for child in widget.winfo_children():
            try:
                text = child.cget("text")
            except Exception:
                text = ""
            if text:
                texts.append(str(text))
            walk(child)

    walk(dialog)
    joined = " | ".join(texts)
    check("提示这是第一次运行", "第一次运行" in joined, joined[:120])
    check("给了退出程序的口子", "退出程序" in joined, joined[:120])
    check("没有「稍后再说」的逃逸口", "稍后再说" not in joined)

    dialog._skip()
    check("取消后请求退出", app._quit_from_setup is True)
    check("取消不算设置成功", dialog.result is False)
    check("取消不写密码", not app.parent.has_password)
    check("取消也不改 enabled", app.parent.enabled is True)
    for _ in range(3):
        try:
            app.update()
        except Exception:
            break
    try:
        alive = bool(app.winfo_exists())
    except tk.TclError:
        alive = False  # 解释器都关了，说明真的退出干净了
    check("主窗口已关闭", not alive)


def test_enter_lock() -> None:
    from quizwin.ui.app import App

    print("\n[4] 设完密码立刻进锁屏")
    fresh_dir()
    app = App(lock_mode=True)
    before = app.setup_required
    app.setup_required = False
    app.update()
    app.parent.set_password("abc123456")
    app.enter_lock_now()
    app.update()

    check("进来时确实还等着设置", before is True)
    check("形态切到锁屏", app.shell_mode == "lock", app.shell_mode)
    check("状态仍是锁定", app.lock.is_locked())
    check("额度条重建完成", app.lock_bar is not None and app.lock_bar.buttons)
    check("没有残留计时条", app.overlay is None)
    check("窗口仍在最前", bool(app.attributes("-topmost")))
    app.destroy()


def test_second_run() -> None:
    from quizwin.ui.app import App

    print("\n[5] 第二次启动：不再问，直接锁")
    app = App(lock_mode=True)
    app.update()
    time.sleep(0.3)
    app.update()

    check("已有密码就不需要设置", app.setup_required is False)
    check("直接是锁屏形态", app.shell_mode == "lock", app.shell_mode)
    check("处于锁定", app.lock.is_locked())
    tops = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    check("没有弹出设置页", not tops, str(tops))
    app.destroy()


def main() -> int:
    print("=" * 56)
    print("首次运行冒烟测试")
    print("=" * 56)
    test_decide()
    test_app_first_run()
    test_setup_dialog()
    test_enter_lock()
    test_second_run()

    print("\n" + "-" * 56)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for item in FAILED:
            print("  ✗", item)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
