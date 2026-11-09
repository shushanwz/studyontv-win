"""设置模式冒烟测试：家长从锁屏进设置、改完回锁屏。

这条路的每一步都有可能把家长关在门外，值得单独测：
- 进设置时输入封锁必须先卸，否则鼠标键盘都用不了，设置页点不动；
- 回锁屏时封锁必须重装，否则一次「打开设置」就等于永久解锁；
- 两个形态的页面集合不同，切换后不能残留旧页面引用。

运行： python tests/settings_mode_smoke.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="quizwin-settings-")) / "data"
(TMP / "banks").mkdir(parents=True)
for _file in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(_file, TMP / "banks" / _file.name)
os.environ["QUIZWIN_DATA"] = str(TMP)
os.environ["QUIZWIN_NO_GUARD"] = "1"

from quizwin.core.parent import ParentControl  # noqa: E402
from quizwin.core.storage import Storage, today_key  # noqa: E402
from quizwin.ui.app import App  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


class FakeGuard:
    def __init__(self):
        self.installed = False
        self.pumps = 0
        self.last_error = ""

    def install(self):
        self.installed = True
        return True

    def uninstall(self):
        self.installed = False

    def pump(self):
        self.pumps += 1

    def keep_foreground(self):
        pass


def main() -> int:
    print("=" * 56)
    print("设置模式冒烟测试")
    print("=" * 56)

    storage = Storage()
    control = ParentControl(storage)
    ok, message, _code = control.set_password("123456")
    if not ok:
        print("设置密码失败：", message)
        return 1
    storage.state["today"] = {"day": today_key(), "credit_ms": 20 * 60_000, "used_ms": 0, "rounds_done": 0}
    storage.save_state()

    app = App(lock_mode=True)
    app.update()

    print("\n[1] 锁屏形态")
    check("初始为锁屏外壳", app.shell_mode == "lock", app.shell_mode)
    check("锁屏下只有答题页", set(app.pages) == {"quiz"}, str(set(app.pages)))
    check("锁屏下没有导航", not app._nav_tabs)
    check("锁屏下有额度条", app.lock_bar is not None)

    guard = FakeGuard()
    app.hardening = guard
    app.engage_guard()
    app.update()
    check("封锁已装", guard.installed)

    print("\n[2] 家长进设置")
    app.open_settings_as_parent()
    app.update()
    check("切到普通外壳", app.shell_mode == "normal", app.shell_mode)
    check("四个页面都在", set(app.pages) == {"quiz", "bank", "rules", "about"}, str(set(app.pages)))
    check("停在规则页", app.current == "rules", app.current)
    check("导航已建", set(app._nav_tabs) == {"quiz", "bank", "rules", "about"}, str(set(app._nav_tabs)))
    check("进设置时放开输入封锁", not guard.installed)
    check("设置模式标记已置", app.settings_mode)
    check("没有额度条残留", app.lock_bar is None)
    check("时钟控件可用", app.clock_label.winfo_exists() == 1)

    print("\n[3] 设置里能切页")
    app.set_page("bank")
    app.update()
    check("切到题库页", app.current == "bank", app.current)
    app.set_page("about")
    app.update()
    check("切到关于页", app.current == "about", app.current)

    print("\n[4] 家长分区保存")
    rules_page = app.pages["rules"]
    check("档位输入框已建", len(rules_page.tier_vars) == 4, str(len(rules_page.tier_vars)))
    check("加固开关已建", set(rules_page.hard_flags) == {"keyboardHook", "clipCursor", "watchdog", "disableTaskMgr"})
    for var, value in zip(rules_page.tier_vars, ("10", "15", "20", "30")):
        var.set(value)
    rules_page.hard_flags["watchdog"].set(False)
    rules_page._save_parent()
    app.update()
    check("档位已写入", app.parent.tiers == [10, 15, 20, 30], str(app.parent.tiers))
    check("加固开关已写入", app.parent.cfg["hardening"]["watchdog"] is False, str(app.parent.cfg["hardening"]))
    rules_page.hard_flags["watchdog"].set(True)
    rules_page._save_parent()
    check("开关能改回来", app.parent.cfg["hardening"]["watchdog"] is True)

    print("\n[5] 返回锁屏")
    app.back_to_lock()
    app.update()
    check("回到锁屏外壳", app.shell_mode == "lock", app.shell_mode)
    check("页面收回到只剩答题", set(app.pages) == {"quiz"}, str(set(app.pages)))
    check("封锁重新装上", guard.installed)
    check("设置模式标记已清", not app.settings_mode)
    check("额度条已重建", app.lock_bar is not None)

    print("\n[6] 设置未消耗额度")
    credit = int(app.storage.state["today"]["credit_ms"])
    used = int(app.storage.state["today"]["used_ms"])
    check("余额未被动过", credit == 20 * 60_000, str(credit))
    check("已用时长未增加", used == 0, str(used))

    app.destroy()

    print("-" * 56)
    print(f"通过 {len(PASSED)} 项")
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for item in FAILED:
            print("  -", item)
        return 1
    print("设置模式行为正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
