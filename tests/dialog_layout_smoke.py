"""对话框布局与延迟回调的冒烟测试。

用控件几何而不是截图来判断：PrintWindow 在窗口 resize 之后会抓到旧的绘制
表面，底部整块发黑，光看图很容易误判成布局缺陷。

运行： python tests/dialog_layout_smoke.py
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

TMP = Path(tempfile.mkdtemp(prefix="quizwin-dlgtest-")) / "data"
(TMP / "banks").mkdir(parents=True)
for _file in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(_file, TMP / "banks" / _file.name)
os.environ["QUIZWIN_DATA"] = str(TMP)

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


def settle(widget, rounds: int = 8) -> None:
    widget.update_idletasks()
    for _ in range(rounds):
        widget.update()
        time.sleep(0.05)


def panel_fits(panel) -> tuple[bool, str]:
    """所有可见子控件都必须落在面板内部。"""
    limit = panel.winfo_height()
    for child in panel.winfo_children():
        if not child.winfo_ismapped():
            continue
        bottom = child.winfo_y() + child.winfo_height()
        if bottom > limit + 1:
            return False, f"{child.winfo_class()} 底边 {bottom} 超出面板 {limit}"
    return True, ""


def button_groups(panel) -> list[tuple[object, list]]:
    groups = []
    for child in panel.winfo_children():
        if child.winfo_class() != "Frame":
            continue
        buttons = [c for c in child.winfo_children() if c.winfo_class() == "Canvas"]
        if buttons:
            groups.append((child, buttons))
    return groups


def main() -> int:
    from run import enable_dpi_awareness

    enable_dpi_awareness()

    from quizwin.ui.app import App
    from quizwin.ui.page_lock import ParentMenu, ParentSetupDialog, PasswordDialog

    print("=" * 56)
    print("对话框布局与延迟回调测试")
    print("=" * 56)

    control = ParentControl(Storage())
    control.set_password("123456")

    app = App()
    settle(app)
    errors: list[BaseException] = []
    app.report_callback_exception = lambda _t, value, _tb: errors.append(value)

    # ---------------- 密码面板 ----------------
    dialog = PasswordDialog(app, app, "家长密码", "提示文字")
    settle(dialog)

    ok, detail = panel_fits(dialog.panel)
    check("密码面板内容不溢出", ok, detail)
    groups = button_groups(dialog.panel)
    check("密码面板有按钮行", len(groups) == 1, str(len(groups)))
    if groups:
        frame, buttons = groups[0]
        check("密码面板三个按钮齐全", len(buttons) == 3, str(len(buttons)))
        check("按钮行贴在面板底部", frame.winfo_y() + frame.winfo_height() <= dialog.panel.winfo_height() + 1)

    # ---------------- 恢复码面板 ----------------
    dialog._build_recovery_panel()
    settle(dialog)

    ok, detail = panel_fits(dialog.panel)
    check("恢复码面板内容不溢出", ok, detail)
    groups = button_groups(dialog.panel)
    check("恢复码面板有按钮行", len(groups) == 1, str(len(groups)))
    if groups:
        frame, buttons = groups[0]
        check("恢复码面板两个按钮齐全", len(buttons) == 2, str(len(buttons)))
        check("重设按钮未被挤出可视区", frame.winfo_y() + frame.winfo_height() <= dialog.panel.winfo_height() + 1)

    labels = [
        c.cget("text")
        for c in dialog.panel.winfo_children()
        if c.winfo_class() == "Label" and c.cget("text")
    ]
    check("恢复码面板有字段标签", "恢复码" in labels and "再输一次" in labels, str(labels))

    dialog.destroy()

    # ---------------- 首次设置向导 ----------------
    control.cfg["password"] = {}
    control.cfg["setupDone"] = False
    control.st.save_state()
    setup = ParentSetupDialog(app, app)
    settle(setup)

    ok, detail = panel_fits(setup.panel)
    check("设置向导内容不溢出", ok, detail)
    groups = button_groups(setup.panel)
    check("设置向导有按钮行", len(groups) == 1, str(len(groups)))
    if groups:
        frame, buttons = groups[0]
        check("设置向导两个按钮齐全", len(buttons) == 2, str(len(buttons)))

    setup.pass1.entry.insert(0, "123456")
    setup.pass2.entry.insert(0, "123456")
    setup._save()
    settle(setup)
    groups = button_groups(setup.panel)
    check("恢复码页有确认按钮", bool(groups) and len(groups[0][1]) == 1)
    check("恢复码已生成", len(setup.recovery) == 9 and setup.recovery[4] == "-", setup.recovery)
    setup.destroy()

    # ---------------- 家长菜单 ----------------
    control.set_password("123456")
    menu = ParentMenu(app, app)
    settle(menu)
    action_buttons = [
        c for c in menu.winfo_children()[0].winfo_children()[-1].winfo_children() if c.winfo_class() == "Canvas"
    ]
    check("家长菜单按钮齐全", len(action_buttons) >= 4, str(len(action_buttons)))
    menu.destroy()

    # ---------------- 销毁后延迟回调不得报错 ----------------
    for _ in range(3):
        victim = PasswordDialog(app, app, "家长密码", "立即销毁")
        victim.destroy()
    for _ in range(20):
        app.update()
        time.sleep(0.05)
    check("销毁后延迟回调已取消，无 bad window path", not errors, str(errors[:1]))

    app.destroy()

    print("\n" + "-" * 56)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print("  失败：", name)
        return 1
    print("对话框布局测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
