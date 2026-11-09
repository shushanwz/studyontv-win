"""家长控制与锁定状态机的冒烟测试：纯逻辑，不启动界面。

运行： python tests/parent_lock_smoke.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quizwin.core.lock import (  # noqa: E402
    LOCKED,
    REASON_STARTUP,
    REASON_TAMPER,
    REASON_TIMEUP,
    UNLOCKED,
    LockController,
)
from quizwin.core.parent import (  # noqa: E402
    MAX_FAILS,
    ParentControl,
    generate_recovery_code,
    make_password_record,
    normalize_code,
    validate_password,
    verify_password_record,
)
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


def fresh_store(tag: str) -> Storage:
    data = Path(tempfile.mkdtemp(prefix=f"quizwin-pl-{tag}-")) / "data"
    (data / "banks").mkdir(parents=True)
    return Storage(data)


class FakeClock:
    """可手动推进的单调时钟。"""

    def __init__(self, start: float = 1000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------- 密码派生


def test_hash() -> None:
    print("\n[密码派生]")
    record = make_password_record("abc123")
    check("正确密码通过", verify_password_record("abc123", record))
    check("错误密码不通过", not verify_password_record("abc124", record))
    check("空记录不通过", not verify_password_record("abc123", {}))
    check("None 记录不通过", not verify_password_record("abc123", None))

    other = make_password_record("abc123")
    check("同密码不同 salt", record["salt"] != other["salt"])
    check("同密码不同哈希", record["hash"] != other["hash"])
    check("哈希不含明文", "abc123" not in json.dumps(record))
    check("记录带算法与迭代次数", record["algo"] == "pbkdf2_sha256" and record["iters"] >= 100000)

    short = make_password_record("abc123", iterations=1000)
    check("支持自定义迭代次数", verify_password_record("abc123", short) and short["iters"] == 1000)


def test_validate() -> None:
    print("\n[密码规则]")
    check("太短被拒", validate_password("12345") is not None)
    check("6 位通过", validate_password("123456") is None)
    check("全同字符被拒", validate_password("aaaaaa") is not None)
    check("首尾空格被拒", validate_password(" 123456 ") is not None)
    check("超长被拒", validate_password("x" * 65) is not None)
    check("字母数字混合通过", validate_password("abc123xy") is None)


# ---------------------------------------------------------------- 家长控制


def test_password_flow() -> None:
    print("\n[密码设置与校验]")
    st = fresh_store("pw")
    pc = ParentControl(st)
    check("初始没有密码", not pc.has_password)
    check("初始未完成设置", not pc.setup_done)

    ok, message, code = pc.set_password("123456")
    check("设置密码成功", ok, message)
    check("恢复码为 4-4 格式", len(code) == 9 and code[4] == "-", code)
    check("设置后标记完成", pc.setup_done)
    check("密码不落明文", "123456" not in st.state_path.read_text(encoding="utf-8"))

    passed, state = pc.check("123456")
    check("正确密码通过", passed and state == "ok")
    passed, state = pc.check("654321")
    check("错误密码被拒", not passed and state == "wrong")

    st2 = fresh_store("pw2")
    pc2 = ParentControl(st2)
    check("无密码时校验返回 nopass", pc2.check("x")[1] == "nopass")


def test_lockout() -> None:
    print("\n[错误锁定]")
    st = fresh_store("fail")
    pc = ParentControl(st)
    pc.set_password("123456")

    states = []
    for _ in range(MAX_FAILS):
        states.append(pc.check("000000")[1])
    check("连续错误被记录", pc.cfg["failCount"] == MAX_FAILS, str(pc.cfg["failCount"]))
    check("第 5 次触发冷却", pc.lockout_seconds() > 0)

    passed, state = pc.check("123456")
    check("冷却期内正确密码也拒绝", not passed and state == "cooldown")

    # 把冷却时间拨到过去，模拟等待结束
    pc.cfg["lockUntil"] = int(time.time()) - 1
    st.save_state()
    passed, state = pc.check("123456")
    check("冷却结束后正确密码通过", passed and state == "ok")
    check("通过后错误计数清零", int(pc.cfg["failCount"]) == 0)

    # 计数落盘，重启不清零
    for _ in range(3):
        pc.check("000000")
    st_b = Storage(st.data_dir)
    pc_b = ParentControl(st_b)
    check("错误计数跨进程保留", int(pc_b.cfg["failCount"]) == 3, str(pc_b.cfg["failCount"]))


def test_recovery() -> None:
    print("\n[恢复码]")
    st = fresh_store("rec")
    pc = ParentControl(st)
    ok, _msg, code = pc.set_password("123456")
    check("设有密码", ok)

    check("恢复码可校验", pc.verify_recovery(code))
    check("恢复码忽略大小写与连字符", pc.verify_recovery(normalize_code(code).lower()))
    check("错误恢复码不通过", not pc.verify_recovery("AAAA-AAAA"))

    ok, msg, new_code = pc.reset_with_recovery(code, "abcdef")
    check("用恢复码重设成功", ok, msg)
    check("重设后新恢复码可用", pc.verify_recovery(new_code))
    check("旧恢复码失效", not pc.verify_recovery(code))
    check("新密码生效", pc.check("abcdef")[0])
    check("旧密码失效", not pc.check("123456")[0])

    ok, _msg, _code = pc.reset_with_recovery(code, "xyz789")
    check("重设后旧码不能再用", not ok)
    check("新码仍可校验", pc.verify_recovery(new_code))

    # used 标记：手工置位后即便码本身正确也要拒绝
    pc.cfg["recovery"]["used"] = True
    st.save_state()
    check("标记用过的码被拒", not pc.reset_with_recovery(new_code, "qwe123")[0])

    ok2, code2 = pc.regenerate_recovery()
    check("可主动换新恢复码", ok2 and pc.verify_recovery(code2))
    check("换码后旧的失效", not pc.verify_recovery(new_code))

    st2 = fresh_store("rec2")
    pc2 = ParentControl(st2)
    pc2.set_password("123456")
    before = int(pc2.cfg["failCount"])
    pc2.reset_with_recovery("BBBB-BBBB", "abcdef")
    check("错误恢复码计入失败次数", int(pc2.cfg["failCount"]) == before + 1)


def test_tiers() -> None:
    print("\n[解锁档位]")
    st = fresh_store("tier")
    pc = ParentControl(st)
    check("默认四档", pc.tiers == [10, 15, 20, 25], str(pc.tiers))
    ok, msg = pc.set_tiers([30, 10, 20])
    check("可自定义并自动排序", ok and pc.tiers == [10, 20, 30], msg)
    check("空档位被拒", not pc.set_tiers([])[0])
    check("越界被拒", not pc.set_tiers([0, 10])[0] or not pc.set_tiers([10, 999])[0])
    check("超过 6 个被拒", not pc.set_tiers([1, 2, 3, 4, 5, 6, 7])[0])


def test_overlay_pos() -> None:
    print("\n[悬浮条位置]")
    st = fresh_store("pos")
    pc = ParentControl(st)
    check("默认无位置", pc.overlay_position() is None)
    pc.save_overlay_position(120, 300)
    st_b = Storage(st.data_dir)
    check("位置跨进程保留", ParentControl(st_b).overlay_position() == (120, 300))


# ---------------------------------------------------------------- 锁定状态机


def test_lock_basic() -> None:
    print("\n[锁定状态机]")
    st = fresh_store("lock")
    clock = FakeClock()
    lk = LockController(st, clock=clock)
    check("初始为锁定", lk.is_locked() and lk.state == LOCKED)
    check("锁定时剩余为 0", lk.remaining_seconds() == 0)
    check("锁定时 tick 不回锁", lk.tick() is None)

    info = lk.unlock(10, "test")
    check("解锁返回时长", info["minutes"] == 10 and info["seconds"] == 600)
    check("解锁后状态正确", lk.is_unlocked())
    check("剩余约 10 分钟", lk.remaining_seconds() == 600, str(lk.remaining_seconds()))
    check("剩余文本格式", lk.remaining_text() == "10:00", lk.remaining_text())

    clock.advance(599)
    check("未到点不回锁", lk.tick() is None)
    check("剩余 1 秒", lk.remaining_seconds() == 1, str(lk.remaining_seconds()))

    clock.advance(1)
    reason = lk.tick()
    check("到点回锁", reason == REASON_TIMEUP and lk.is_locked(), str(reason))
    check("回锁原因落盘", lk.cfg["lastLockReason"] == REASON_TIMEUP)
    check("回锁后剩余归零", lk.remaining_seconds() == 0)
    check("重复回锁不重复计数", lk.force_lock() is False)

    lk.unlock(5, "test")
    lk.unlock(5, "test")
    check("重复调用 unlock 覆盖为最后一次", lk.remaining_seconds() == 300)


def test_lock_extend() -> None:
    print("\n[加时与家长解锁]")
    st = fresh_store("ext")
    clock = FakeClock()
    lk = LockController(st, clock=clock)

    lk.unlock(10, "answer")
    clock.advance(300)
    lk.extend(5, "parent")
    check("解锁中加时累加", lk.remaining_seconds() == 600, str(lk.remaining_seconds()))

    lk.force_lock()
    lk.extend(15, "parent")
    check("锁定时加时等于解锁", lk.is_unlocked() and lk.remaining_seconds() == 900)

    st2 = fresh_store("tomorrow")
    lk2 = LockController(st2, clock=FakeClock())
    info = lk2.unlock_until_tomorrow()
    check("解锁到明天为正数分钟", info["minutes"] > 0)
    check("解锁到明天长于 1 分钟", lk2.remaining_seconds() > 60)


def test_crash_recovery() -> None:
    print("\n[异常退出恢复]")
    st = fresh_store("crash")
    clock = FakeClock()
    lk = LockController(st, clock=clock)
    lk.unlock(20, "answer")
    check("解锁中", lk.is_unlocked())

    # 模拟进程被强杀：状态留在磁盘上，新实例读回来
    st_b = Storage(st.data_dir)
    check("磁盘上状态仍是 unlocked", st_b.state["lock"]["state"] == UNLOCKED)
    lk_b = LockController(st_b, clock=FakeClock())
    info = lk_b.recover_from_crash()
    check("识别为异常退出", info["abnormal"] and info["wasUnlocked"])
    check("启动后强制回锁", lk_b.is_locked())
    check("异常次数累加", int(st_b.state["lock"]["abnormalExit"]) == 1, str(st_b.state["lock"]["abnormalExit"]))
    check("恢复原因记为启动", st_b.state["lock"]["lastLockReason"] == REASON_STARTUP)


def test_tamper() -> None:
    print("\n[时钟回拨]")
    st = fresh_store("tamper")
    clock = FakeClock()
    lk = LockController(st, clock=clock)
    lk.unlock(25, "answer")
    lk.heartbeat()

    # 把上次心跳时间伪造成 10 分钟后，等价于系统时间被往回调了 10 分钟
    lk.cfg["lastSeenWall"] = int(time.time()) + 600
    st.save_state()

    result = lk.heartbeat()
    check("检测到时间回拨", result == REASON_TAMPER, str(result))
    check("回拨后立即回锁", lk.is_locked())
    check("回拨次数累加", int(lk.cfg["tamperCount"]) == 1)

    st2 = fresh_store("tamper2")
    lk2 = LockController(st2, clock=FakeClock())
    lk2.unlock(10, "answer")
    lk2.cfg["lastSeenWall"] = int(time.time()) - 30
    st2.save_state()
    check("小幅校时不误判", lk2.heartbeat() is None and lk2.is_unlocked())


def test_heartbeat_deadline() -> None:
    print("\n[心跳落盘]")
    st = fresh_store("hb")
    clock = FakeClock()
    lk = LockController(st, clock=clock)
    lk.unlock(10, "answer")
    clock.advance(120)
    lk.heartbeat()
    wall_left = int(st.state["lock"]["deadlineWall"]) - int(time.time())
    check("落盘到期时刻与内存一致", abs(wall_left - 480) <= 2, str(wall_left))


# ---------------------------------------------------------------- 状态迁移


def test_state_migration() -> None:
    print("\n[老状态文件迁移]")
    data = Path(tempfile.mkdtemp(prefix="quizwin-pl-mig-")) / "data"
    (data / "banks").mkdir(parents=True)
    legacy = {
        "schema": 1,
        "active_bank": "",
        "theme": "light",
        "today": {"day": "", "credit_ms": 60000, "used_ms": 0, "rounds_done": 1},
        "custom_field": {"keep": True},
    }
    (data / "state.json").write_text(json.dumps(legacy), encoding="utf-8")

    st = Storage(data)
    check("补齐 parent 节", isinstance(st.state.get("parent"), dict))
    check("补齐 lock 节", isinstance(st.state.get("lock"), dict))
    check("默认四档", st.state["parent"]["tiers"] == [10, 15, 20, 25])
    check("默认加固开关就位", st.state["parent"]["hardening"]["keyboardHook"] is True)
    check("锁定初始为 locked", st.state["lock"]["state"] == LOCKED)
    check("保留原有主题", st.state["theme"] == "light")
    check("保留原有余额", st.state["today"]["credit_ms"] == 60000)
    check("保留未知字段", st.state.get("custom_field") == {"keep": True})
    check("schema 升到 2", st.state.get("schema") == 2)


def test_damaged_lock_block() -> None:
    print("\n[字段损坏容错]")
    data = Path(tempfile.mkdtemp(prefix="quizwin-pl-bad-")) / "data"
    (data / "banks").mkdir(parents=True)
    (data / "state.json").write_text(
        json.dumps({"lock": "oops", "parent": 123, "today": {"credit_ms": "abc"}}), encoding="utf-8"
    )
    st = Storage(data)
    check("lock 损坏时回落默认", st.state["lock"]["state"] == LOCKED)
    check("parent 损坏时回落默认", isinstance(st.state["parent"], dict) and "tiers" in st.state["parent"])
    check("today 数值损坏归零", st.state["today"]["credit_ms"] == 0)

    clock = FakeClock()
    lk = LockController(st, clock=clock)
    check("损坏状态下仍判定为锁定", lk.is_locked())


def main() -> int:
    print("=" * 56)
    print("家长控制 · 冒烟测试")
    print("=" * 56)

    test_hash()
    test_validate()
    test_password_flow()
    test_lockout()
    test_recovery()
    test_tiers()
    test_overlay_pos()
    test_lock_basic()
    test_lock_extend()
    test_crash_recovery()
    test_tamper()
    test_heartbeat_deadline()
    test_state_migration()
    test_damaged_lock_block()

    print("\n" + "-" * 56)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print("  失败：", name)
        return 1
    print("家长控制逻辑测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
