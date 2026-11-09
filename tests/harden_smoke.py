"""系统层封锁与看门狗的冒烟测试。

覆盖两部分：
1. 纯函数：哪些按键该吞、看门狗的重启决策、退出令牌有效期。
2. 真实调用：装/卸键盘钩子、进程存活探测。

不测「按 Alt+Tab 是否真被拦住」，那需要人手按，机器验不了；
能验的是钩子装得上、吞键判定正确、卸得干净。

运行： python tests/harden_smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quizwin.core.storage import Storage  # noqa: E402
from quizwin.core.parent import ParentControl  # noqa: E402
from quizwin.winapi import harden, watchdog  # noqa: E402
from quizwin.winapi.harden import HardenOptions, Hardening, block_reason  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [!!] {name} {detail}")


def fake_down(*pressed: int):
    """构造一个「这些键正被按住」的探测器，替代真实的 GetAsyncKeyState。"""
    held = set(pressed)
    return lambda vk: vk in held


def make_storage(password: bool = True) -> Storage:
    tmp = Path(tempfile.mkdtemp(prefix="quizwin-harden-"))
    (tmp / "banks").mkdir()
    os.environ["QUIZWIN_DATA"] = str(tmp)
    storage = Storage()
    if password:
        ParentControl(storage).set_password("123456")
    return storage


def test_block_reason() -> None:
    print("\n[1] 按键拦截判定")
    nowin = fake_down()
    check("单独按 Win 被拦", block_reason(harden.VK_LWIN, nowin) == "win")
    check("右 Win 也被拦", block_reason(harden.VK_RWIN, nowin) == "win")
    check("Win 按下时字母键一并拦", block_reason(ord("E"), fake_down(harden.VK_LWIN)) == "win-combo")
    check("Alt+Tab 被拦", block_reason(harden.VK_TAB, fake_down(harden.VK_MENU)) == "alt-tab")
    check("Alt+F4 被拦", block_reason(harden.VK_F4, fake_down(harden.VK_MENU)) == "alt-f4")
    check("Alt+Esc 被拦", block_reason(harden.VK_ESCAPE, fake_down(harden.VK_MENU)) == "alt-esc")
    check("Ctrl+Esc 被拦", block_reason(harden.VK_ESCAPE, fake_down(harden.VK_CONTROL)) == "ctrl-esc")
    check(
        "Ctrl+Shift+Esc 被拦",
        block_reason(harden.VK_ESCAPE, fake_down(harden.VK_CONTROL, harden.VK_SHIFT)) == "ctrl-shift-esc",
    )
    check("左侧 Alt 也算 Alt", block_reason(harden.VK_TAB, fake_down(harden.VK_LMENU)) == "alt-tab")
    check("右侧 Ctrl 也算 Ctrl", block_reason(harden.VK_ESCAPE, fake_down(harden.VK_RCONTROL)) == "ctrl-esc")
    check("普通字母放行", block_reason(ord("A"), nowin) == "")
    check("数字放行", block_reason(ord("1"), nowin) == "")
    check("空格放行", block_reason(0x20, nowin) == "")
    check("单独 Esc 放行", block_reason(harden.VK_ESCAPE, nowin) == "")
    check("单独 F4 放行", block_reason(harden.VK_F4, nowin) == "")
    check("Tab 单独放行", block_reason(harden.VK_TAB, nowin) == "")
    check("Enter 放行", block_reason(0x0D, nowin) == "")


def test_hardening_lifecycle() -> None:
    print("\n[2] 钩子安装与卸载")
    holder = {"hwnd": 0}
    hard = Hardening(lambda: holder["hwnd"], HardenOptions(keyboard_hook=True, clip_cursor=False))
    check("初始未安装", not hard.installed)
    ok = hard.install()
    if ok:
        check("安装成功", hard.installed)
        check("重复安装幂等", hard.install() is True and hard.installed)
        hard.uninstall()
        check("卸载干净", not hard.installed)
        check("重复卸载不报错", hard._hook is None)
        # 再装一次，确认能反复用（解锁 → 回锁 会走这条路）
        check("可再次安装", hard.install() and hard.installed)
        hard.uninstall()
        check("二次卸载干净", not hard.installed)
    else:
        # 某些受限会话（如服务态）装不上钩子，如实记录失败原因，不当成测试失败
        print(f"  注意：本会话装不上键盘钩子，原因：{hard.last_error}")
        check("安装失败时给出原因", bool(hard.last_error))


def test_pid_tools() -> None:
    print("\n[3] 进程存活探测")
    check("自己活着", watchdog.pid_alive(os.getpid()))
    check("不存在的进程判死", not watchdog.pid_alive(999_999))
    check("pid 为 0 判死", not watchdog.pid_alive(0))
    check("kill 不存在的进程返回 False", watchdog.kill_pid(999_999) is False)


def test_exit_token() -> None:
    print("\n[4] 正常退出令牌")
    root = Path(tempfile.mkdtemp(prefix="quizwin-token-"))
    check("初始无令牌", not watchdog.token_fresh(root))
    watchdog.write_exit_token(root)
    check("写入后有效", watchdog.token_fresh(root))
    # 手工把时间戳改老，验证过期判定
    token = root / "data" / "runtime" / watchdog.TOKEN_NAME
    old = int((time.time() - watchdog.EXIT_TOKEN_TTL - 10) * 1000)
    token.write_text(str(old), encoding="utf-8")
    check("过期令牌无效", not watchdog.token_fresh(root))
    token.write_text("不是数字", encoding="utf-8")
    check("损坏令牌不抛异常且判无效", watchdog.token_fresh(root) is False)
    watchdog.write_exit_token(root)
    watchdog.consume_exit_token(root)
    check("消费后文件消失", not token.exists())
    check("消费后再查无效", not watchdog.token_fresh(root))


def test_relaunch_decision() -> None:
    print("\n[5] 重启决策")
    root = Path(tempfile.mkdtemp(prefix="quizwin-relaunch-"))
    (root / "data" / "banks").mkdir(parents=True)
    os.environ["QUIZWIN_DATA"] = str(root / "data")
    storage = Storage()

    ok, reason = watchdog.should_relaunch(root)
    check("没有状态文件不拉起", not ok and "状态文件" in reason, reason)

    Control = ParentControl(storage)
    Control.cfg["enabled"] = False
    storage.save_state()
    ok, reason = watchdog.should_relaunch(root)
    check("家长控制关闭不拉起", not ok and "未启用" in reason, reason)

    Control.cfg["enabled"] = True
    Control.set_password("123456")
    storage.save_state()
    ok, reason = watchdog.should_relaunch(root)
    check("有密码且启用则拉起", ok, reason)

    watchdog.write_exit_token(root)
    ok, reason = watchdog.should_relaunch(root)
    check("有正常退出令牌则不拉起", not ok and "令牌" in reason, reason)
    watchdog.consume_exit_token(root)

    # 状态文件损坏时宁可不动：拉起一个读不到配置的程序没有意义
    (root / "data" / "state.json").write_text("{坏掉了", encoding="utf-8")
    ok, reason = watchdog.should_relaunch(root)
    check("状态文件损坏不拉起", not ok, reason)


def test_watchdog_client_defaults() -> None:
    print("\n[6] 守护客户端")
    root = Path(tempfile.mkdtemp(prefix="quizwin-client-"))
    client = watchdog.Watchdog(root)
    check("未启动时 running 为假", not client.running)
    check("初始无 pid", client.pid == 0)
    # 不真的启动守护：一旦启动，测试进程退出时它会把锁屏拉起来
    check("stop 空操作不报错", client.stop(graceful=False) is None)


def main() -> int:
    print("=" * 56)
    print("系统层封锁冒烟测试")
    print("=" * 56)
    test_block_reason()
    test_hardening_lifecycle()
    test_pid_tools()
    test_exit_token()
    test_relaunch_decision()
    test_watchdog_client_defaults()

    print("-" * 56)
    print(f"通过 {len(PASSED)} 项")
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for item in FAILED:
            print("  -", item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
