"""锁屏静音冒烟测试：只验逻辑，用假后端，不碰真实系统音量。

要覆盖的四种情形，都是「凭直觉写就会写错」的那种：
  * 本来没静音 → 锁屏关掉、解锁还原；
  * 本来已静音（家长自己关的）→ 记一笔但不改，解锁也不许替他打开；
  * 重复调用（回锁后又回锁）→ 不能来回翻转；
  * 上次没收尾（崩溃、拔电）→ 启动时 recover 把声音还回去。

运行： python tests/mute_smoke.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="quizwin-mute-")) / "data"
(TMP / "banks").mkdir(parents=True)
for _file in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(_file, TMP / "banks" / _file.name)
os.environ["QUIZWIN_DATA"] = str(TMP)
os.environ["QUIZWIN_NO_GUARD"] = "1"

from quizwin.core.lock import LockController  # noqa: E402
from quizwin.core.mute import KEY, MuteGuard  # noqa: E402
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


class StubAudio:
    """假声卡：可以指定能否读、能否写，用来逼出降级路径。"""

    def __init__(self, muted: bool = False, readable: bool = True, writable: bool = True):
        self.muted = muted
        self.readable = readable
        self.writable = writable
        self.calls: list[bool] = []
        self.last_error = ""

    def is_muted(self):
        if not self.readable:
            self.last_error = "没有可用的播放设备"
            return None
        return self.muted

    def set_mute(self, muted: bool) -> bool:
        self.calls.append(bool(muted))
        if not self.writable:
            self.last_error = "SetMute 被系统拒绝"
            return False
        self.muted = bool(muted)
        return True


def fresh_storage() -> Storage:
    state_file = TMP / "state.json"
    if state_file.exists():
        state_file.unlink()
    return Storage()


def main() -> int:
    print("\n[1] 本来没静音：锁屏关掉、解锁还原")
    st = fresh_storage()
    lock = LockController(st)
    audio = StubAudio(muted=False)
    guard = MuteGuard(lock, backend=audio)

    check("初始没有记号", not guard.engaged() and st.state["lock"][KEY] is None)
    check("锁屏时返回 muted", guard.engage() == "muted")
    check("系统已静音", audio.muted is True)
    check("已记下原状态（0=本来没静音）", st.state["lock"][KEY] == 0)
    check("记号已落盘", KEY in st.state["lock"])

    st2 = Storage()  # 重新读盘，确认不是只存在内存里
    check("换一个实例仍能看到记号", LockController(st2).cfg.get(KEY) == 0)

    check("解锁时还原", guard.release() is True)
    check("系统已取消静音", audio.muted is False)
    check("记号已清空", st.state["lock"][KEY] is None)
    check("重复解锁不再动声音", guard.release() is False)

    print("\n[2] 本来已静音：只记账，绝不自作主张打开声音")
    st = fresh_storage()
    lock = LockController(st)
    audio = StubAudio(muted=True)
    guard = MuteGuard(lock, backend=audio)

    check("锁屏时返回 already", guard.engage() == "already")
    check("没有多余的声音调用", audio.calls == [], str(audio.calls))
    check("记号记为 1", st.state["lock"][KEY] == 1)
    check("解锁时不动声音", guard.release() is False)
    check("系统仍是静音", audio.muted is True)
    check("记号已清空", st.state["lock"][KEY] is None)

    print("\n[3] 重复调用：不能来回翻转")
    st = fresh_storage()
    lock = LockController(st)
    audio = StubAudio(muted=False)
    guard = MuteGuard(lock, backend=audio)
    guard.engage()
    guard.engage()
    guard.engage()
    check("三次锁屏只动一次声音", audio.calls == [True], str(audio.calls))
    check("记号仍记为 0", st.state["lock"][KEY] == 0)

    print("\n[4] 上次没收尾：启动时 recover 把声音还回去")
    st = fresh_storage()
    lock = LockController(st)
    audio = StubAudio(muted=False)
    guard = MuteGuard(lock, backend=audio)
    guard.engage()
    # 模拟「进程被杀」：不复位内存，只换成新实例（相当于重新启动）
    audio_after = StubAudio(muted=True)
    st_after = Storage()
    guard2 = MuteGuard(LockController(st_after), backend=audio_after)
    check("新实例启动时看到残留记号", guard2.engaged())
    check("recover 还原了声音", guard2.recover() is True)
    check("系统已取消静音", audio_after.muted is False)
    check("残留记号已清除", st_after.state["lock"][KEY] is None)
    check("没有残留时 recover 什么也不做", guard2.recover() is False)

    print("\n[5] 读不到设备（无声卡）：不写记号，锁屏照常")
    st = fresh_storage()
    lock = LockController(st)
    audio = StubAudio(muted=False, readable=False)
    guard = MuteGuard(lock, backend=audio)
    check("返回 unsupported", guard.engage() == "unsupported")
    check("没有乱写记号", st.state["lock"][KEY] is None)
    check("没有调用过写入", audio.calls == [], str(audio.calls))
    check("错误原因记下来了", "播放设备" in guard.last_error, guard.last_error)
    check("这种情况下解锁也不会动声音", guard.release() is False)

    print("\n[6] 写入被拒：同样不写记号")
    st = fresh_storage()
    lock = LockController(st)
    audio = StubAudio(muted=False, writable=False)
    guard = MuteGuard(lock, backend=audio)
    check("返回 failed", guard.engage() == "failed")
    check("没有写记号", st.state["lock"][KEY] is None)
    check("尝试过一次", audio.calls == [True], str(audio.calls))

    print("\n[7] 默认后端：测试环境下不会碰真声卡")
    st = fresh_storage()
    guard = MuteGuard(LockController(st))
    check("QUIZWIN_NO_GUARD 时用假后端", type(guard._audio).__name__ == "NullAudio", type(guard._audio).__name__)

    print("\n" + "-" * 56)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print("  失败：", name)
        return 1
    print("锁屏静音冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
