"""锁屏界面冒烟测试：真实建窗，验证锁定 → 兑换 → 计时条 → 回锁这条链路。

只测界面与状态联动，不做系统加固（Alt+Tab 拦截、看门狗另见 harden_smoke 与
guard_wiring_smoke）。

运行： python tests/lock_ui_smoke.py [截图路径]
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

TMP = Path(tempfile.mkdtemp(prefix="quizwin-lockui-")) / "data"
(TMP / "banks").mkdir(parents=True)
for _file in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(_file, TMP / "banks" / _file.name)
os.environ["QUIZWIN_DATA"] = str(TMP)
# 测试进程绝不能真装键盘钩子、真起看门狗：那会把跑测试的这台机器锁住
os.environ["QUIZWIN_NO_GUARD"] = "1"

from quizwin.core.parent import ParentControl  # noqa: E402
from quizwin.core.storage import Storage, today_key  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    shot = Path(args[0]) if args else None

    storage = Storage()
    control = ParentControl(storage)
    ok, message, _code = control.set_password("123456")
    if not ok:
        print("设置密码失败：", message)
        return 1
    if "--light" in sys.argv:
        storage.state["theme"] = "light"
    # 必须写成「今天」，否则第一次读状态会按跨天逻辑把余额清零
    storage.state["today"]["day"] = today_key()
    storage.state["today"]["credit_ms"] = 12 * 60_000
    storage.save_state()

    from run import enable_dpi_awareness

    enable_dpi_awareness()

    from quizwin.ui.app import App

    print("=" * 56)
    print("锁屏界面冒烟测试")
    print("=" * 56)

    app = App(lock_mode=True)
    app.update()
    time.sleep(0.35)
    app.update()

    check("以锁屏形态启动", app.lock_mode is True)
    check("只有答题页", list(app.pages.keys()) == ["quiz"], str(list(app.pages.keys())))
    check("额度条已挂载", app.lock_bar is not None)
    check("启动时处于锁定", app.lock.is_locked())
    check("窗口为全屏无边框", bool(app.overrideredirect()))
    check("初始没有计时条", app.overlay is None)

    bar = app.lock_bar
    check("档位按钮数量与配置一致", len(bar.buttons) == len(app.parent.tiers), str(len(bar.buttons)))
    check("余额 12 分钟够开第一档", bar.buttons[10].enabled, bar.buttons[10].label)
    check("不够的档位置灰", not bar.buttons[15].enabled, bar.buttons[15].label)
    check("不足提示写清差额", "差 3" in bar.buttons[15].label, bar.buttons[15].label)
    check("余额文案已渲染", "12" in bar.headline.cget("text"), bar.headline.cget("text"))

    if shot is not None:
        try:
            from winshot import capture, window_handle

            shot.parent.mkdir(parents=True, exist_ok=True)
            if "--question" in sys.argv or "--answer" in sys.argv:
                quiz = app.pages["quiz"]
                quiz.begin()
                app.update()
                time.sleep(0.4)
                app.update()
                if "--answer" in sys.argv:
                    question = quiz.round.get("question") or {}
                    correct = question.get("correctIndices") or []
                    quiz.choose(correct[0] if correct else 0)
                    quiz.submit()
                    app.update()
                    time.sleep(0.4)
                    app.update()
            capture(window_handle(app), shot)
            print(f"  已截图： {shot}")
        except Exception as exc:  # pragma: no cover
            print("  截图失败：", exc)

    if "--question" in sys.argv or "--answer" in sys.argv:
        app.destroy()
        return 0

    # ---------------- 兑换 ----------------

    credit_before = int(app.storage.state["today"]["credit_ms"])
    app.request_unlock(10)
    app.update()

    check("兑换后进入解锁状态", app.lock.is_unlocked())
    check("计时条已创建", app.overlay is not None)
    check("倒计时约 10 分钟", 590 <= app.lock.remaining_seconds() <= 600, str(app.lock.remaining_seconds()))
    check("主窗口已收起", app.state() == "withdrawn", app.state())
    check(
        "余额扣掉 10 分钟",
        int(app.storage.state["today"]["credit_ms"]) == credit_before - 600_000,
        str(app.storage.state["today"]["credit_ms"]),
    )
    check(
        "已用时长同步增加",
        int(app.storage.state["today"]["used_ms"]) == 600_000,
        str(app.storage.state["today"]["used_ms"]),
    )
    check("计时条显示 mm:ss", app.overlay.clock.cget("text") in ("10:00", "09:59"), app.overlay.clock.cget("text"))

    # ---------------- 计时条尺寸与闪烁 ----------------

    overlay = app.overlay
    app.update()
    check(
        "时钟高度够，不被窗口切掉",
        overlay.clock.winfo_height() >= overlay.clock.winfo_reqheight(),
        f"{overlay.clock.winfo_height()} < {overlay.clock.winfo_reqheight()}",
    )
    check(
        "时钟宽度够",
        overlay.clock.winfo_width() >= overlay.clock.winfo_reqwidth(),
        f"{overlay.clock.winfo_width()} < {overlay.clock.winfo_reqwidth()}",
    )
    check(
        "窗口高度按字体算过",
        overlay.winfo_height() >= overlay._inner.winfo_reqheight(),
        f"{overlay.winfo_height()} < {overlay._inner.winfo_reqheight()}",
    )
    check("平时写「剩余时间」", overlay.caption.cget("text") == "剩余时间", overlay.caption.cget("text"))

    # 心跳每 600ms 会按真实剩余时间刷一次，把刚放大的窗口打回 1 倍。机器慢一点
    # （比如批量跑测试时）就会在这里翻车，所以量尺寸期间先停掉它
    app._cancel_overlay_job()

    overlay.refresh(45)
    check("60 秒内提示「快结束了」", overlay.caption.cget("text") == "快结束了", overlay.caption.cget("text"))

    base_size = overlay._size
    base_center = overlay._center()
    overlay.refresh(29)
    app.update()
    zoom_size = overlay._size
    zoom_center = overlay._center()
    ratio_w = zoom_size[0] / base_size[0]
    ratio_h = zoom_size[1] / base_size[1]
    check(
        "最后 30 秒整条放大到三倍",
        ratio_w >= 2.9 and ratio_h >= 2.9,
        f"{base_size} → {zoom_size}（宽 {ratio_w:.2f} 倍 / 高 {ratio_h:.2f} 倍）",
    )
    # 条子默认停在右上角附近，放大三倍后必然要往里让位（不然出屏），
    # 所以这里不要求像素级不动，只要求它「还在原来那一带」，没跑到屏幕中央
    check(
        "放大后仍贴在右上角一带",
        zoom_center[0] > overlay.winfo_screenwidth() * 0.6
        and zoom_center[1] < overlay.winfo_screenheight() * 0.4,
        f"{base_center} → {zoom_center}，屏幕 {overlay.winfo_screenwidth()}x{overlay.winfo_screenheight()}",
    )
    check(
        "放大后时钟没被裁掉",
        overlay.clock.winfo_height() >= overlay.clock.winfo_reqheight()
        and overlay.clock.winfo_width() >= overlay.clock.winfo_reqwidth(),
        f"{overlay.clock.winfo_width()}x{overlay.clock.winfo_height()} / "
        f"{overlay.clock.winfo_reqwidth()}x{overlay.clock.winfo_reqheight()}",
    )
    check(
        "放大后窗口仍在屏幕内",
        overlay.winfo_x() + zoom_size[0] <= overlay.winfo_screenwidth()
        and overlay.winfo_y() + zoom_size[1] <= overlay.winfo_screenheight(),
        f"({overlay.winfo_x()},{overlay.winfo_y()}) {zoom_size}",
    )

    first = overlay.clock.cget("fg")
    overlay.refresh(29)
    second = overlay.clock.cget("fg")
    check("最后 30 秒开始闪（颜色每秒翻转）", first != second, f"{first} / {second}")
    check("闪的同时提醒保存", overlay.caption.cget("text") == "记得保存", overlay.caption.cget("text"))
    overlay.refresh(9)
    check("最后 10 秒改说「即将回锁」", overlay.caption.cget("text") == "即将回锁", overlay.caption.cget("text"))
    overlay.refresh(300)
    app.update()
    check("回到 5 分钟时不再闪", overlay.caption.cget("text") == "剩余时间", overlay.caption.cget("text"))
    check(
        "回到 5 分钟时缩回原尺寸",
        overlay._size == base_size,
        f"{overlay._size} / 原 {base_size}",
    )
    check("一位数小时也能显示", overlay._format(3725) == "1:02:05", overlay._format(3725))
    overlay.refresh(59)
    app.update()
    check(
        "位数变少后照样完整",
        overlay.clock.winfo_width() >= overlay.clock.winfo_reqwidth(),
        f"{overlay.clock.winfo_width()} / {overlay.clock.winfo_reqwidth()}",
    )

    # ---------------- 到点回锁 ----------------

    app.lock._deadline = app.lock._clock() - 1
    app._tick_overlay()
    app.update()

    check("到点后回到锁定", app.lock.is_locked())
    check("计时条已销毁", app.overlay is None)
    check("主窗口重新显示", app.state() == "normal", app.state())
    check("回锁原因记为时间到", app.storage.state["lock"]["lastLockReason"] == "timeup")
    check("回锁后把系统声音关掉", app.mute.engaged() and app.storage.state["lock"]["muteBefore"] == 0)
    check("声音状态落到 state.json", app.storage.state["lock"]["muteBefore"] in (0, 1))

    # ---------------- 提前结束 ----------------

    before_credit = int(app.storage.state["today"]["credit_ms"])
    app.request_unlock(25)
    app.update()
    check("余额不足时不放行", app.lock.is_locked())
    check("余额不足时余额不变", int(app.storage.state["today"]["credit_ms"]) == before_credit)

    # ---------------- 家长解锁 ----------------

    check("静音记号还在（解锁前）", app.mute.engaged())
    from quizwin.ui.page_lock import PARENT_UNLOCK_MINUTES  # noqa: E402

    check("家长临时解锁是 45 分钟", PARENT_UNLOCK_MINUTES == 45, str(PARENT_UNLOCK_MINUTES))
    app.parent_unlock(PARENT_UNLOCK_MINUTES)
    app.update()
    check("家长可直接解锁", app.lock.is_unlocked())
    check("解锁时长按 45 分钟计", 44 * 60 <= app.lock.remaining_seconds() <= 45 * 60, str(app.lock.remaining_seconds()))
    check("家长解锁不动答题余额", int(app.storage.state["today"]["credit_ms"]) == before_credit)
    check("解锁后解除静音", not app.mute.engaged() and app.storage.state["lock"]["muteBefore"] is None)
    check("解锁后声音恢复", not app.mute._audio.muted)
    app.end_unlock_early()
    app.update()
    check("提前结束立即回锁", app.lock.is_locked())
    check("提前结束也销毁计时条", app.overlay is None)
    check("结束回锁也静音", app.mute.engaged())

    app.destroy()

    print("\n" + "-" * 56)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print("  失败：", name)
        return 1
    print("锁屏界面冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
