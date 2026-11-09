"""封锁时序冒烟测试：验证「锁屏时装、解锁时卸、回锁时重装」。

这一步最容易写错，而且错了后果很具体：
- 解锁时忘了卸 → 家长自己也用不了电脑；
- 回锁时忘了装 → 锁屏变成一个随便 Alt+Tab 就能走掉的全屏窗口。

用替身对象验证调用时序，不真装钩子、不真起守护进程。

运行： python tests/guard_wiring_smoke.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="quizwin-guard-")) / "data"
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
        self.focused = 0
        self.last_error = ""

    def install(self) -> bool:
        self.installed = True
        return True

    def uninstall(self) -> None:
        self.installed = False

    def pump(self) -> None:
        if self.installed:
            self.pumps += 1

    def keep_foreground(self) -> None:
        self.focused += 1


class FakeDog:
    def __init__(self):
        self.running = False
        self.starts = 0
        self.stops: list[bool] = []

    def start(self) -> bool:
        self.running = True
        self.starts += 1
        return True

    def stop(self, graceful: bool = True) -> None:
        self.running = False
        self.stops.append(graceful)


def main() -> int:
    print("=" * 56)
    print("封锁时序冒烟测试")
    print("=" * 56)

    storage = Storage()
    control = ParentControl(storage)
    ok, message, _code = control.set_password("123456")
    if not ok:
        print("设置密码失败：", message)
        return 1
    storage.state["today"] = {
        "day": today_key(),
        "credit_ms": 30 * 60_000,
        "used_ms": 0,
        "rounds_done": 0,
    }
    storage.save_state()

    app = App(lock_mode=True)
    app.update()

    print("\n[1] 测试模式")
    check("未真装键盘钩子", app.hardening is None)
    check("未真起看门狗", app.watchdog is None)

    guard, dog = FakeGuard(), FakeDog()
    app.hardening = guard
    app.watchdog = dog

    print("\n[2] 进入锁屏")
    app.engage_guard()
    app.update()
    check("锁屏时装上输入封锁", guard.installed)
    check("锁屏时拉起看门狗", dog.running and dog.starts == 1)
    check("装好后立即抢占前台", guard.focused >= 1)

    print("\n[3] 解锁自由玩")
    app.request_unlock(10)
    app.update()
    check("解锁后进入计时态", app.lock.is_unlocked())
    check("解锁瞬间卸掉输入封锁", not guard.installed)
    check("解锁后停掉看门狗", not dog.running)
    check("解锁不是正常退出，不能写退出令牌", dog.stops == [False], str(dog.stops))

    print("\n[4] 到点回锁")
    app.lock._deadline = app.lock._clock() - 1
    app._tick_overlay()
    app.update()
    check("到点后回到锁定态", app.lock.is_locked())
    check("回锁后重新装上封锁", guard.installed)
    check("回锁后看门狗重新拉起", dog.running and dog.starts == 2)

    print("\n[5] 锁屏心跳")
    before = guard.pumps
    for _ in range(4):
        app._tick_lock()
    app.update()
    check("心跳会周期性抢回前台", guard.pumps > before, f"{before} → {guard.pumps}")

    print("\n[6] 提前结束与家长解锁")
    app.request_unlock(10)
    app.update()
    check("再次解锁卸掉封锁", not guard.installed)
    app.end_unlock_early()
    app.update()
    check("提前结束后回锁并重装封锁", app.lock.is_locked() and guard.installed)

    app.parent_unlock(5)
    app.update()
    check("家长解锁同样会卸掉封锁", app.lock.is_unlocked() and not guard.installed)

    print("\n[7] 正常退出")
    app.release_guard(graceful=True)
    check("退出时卸掉封锁", not guard.installed)
    check("退出时告诉看门狗别拉回来", dog.stops[-1] is True, str(dog.stops))

    app.destroy()

    print("-" * 56)
    print(f"通过 {len(PASSED)} 项")
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for item in FAILED:
            print("  -", item)
        return 1
    print("封锁时序全部正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
