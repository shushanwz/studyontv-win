"""看门狗重启行为的真实验证。

真的起一个守护进程，真的把它的「父进程」杀掉，看它有没有在几秒内决定重启锁屏。
用 QUIZWIN_GUARD_DRY=1 让重启只留痕不真拉起——否则跑这个测试会把人正用着的桌面锁住。

运行： python tests/guard_relaunch_smoke.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "quizwin" / "winapi" / "watchdog.py"
PY = sys.executable

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def make_root(with_password: bool = True) -> Path:
    root = Path(tempfile.mkdtemp(prefix="quizwin-dog-"))
    data = root / "data"
    (data / "banks").mkdir(parents=True)
    state = {
        "schema": 2,
        "parent": {
            "enabled": True,
            "setupDone": with_password,
            "password": {"algo": "pbkdf2_sha256", "iters": 260000, "salt": "00", "hash": "00"} if with_password else {},
        },
        "lock": {"state": "locked"},
    }
    (data / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return root


def start_guard(root: Path, parent_pid: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["QUIZWIN_GUARD_DRY"] = "1"
    return subprocess.Popen(
        [PY, str(GUARD), "--guard", "--root", str(root), "--parent-pid", str(parent_pid)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for(path: Path, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.2)
    return False


def case_killed(root: Path) -> None:
    print("\n[1] 父进程被强杀")
    victim = subprocess.Popen([PY, "-c", "import time; time.sleep(60)"])
    guard = start_guard(root, victim.pid)
    time.sleep(2.2)  # 让守护进入循环
    check("守护进程存活", guard.poll() is None)
    victim.kill()
    victim.wait(timeout=5)

    mark = root / "data" / "runtime" / "relaunch.dry"
    fired = wait_for(mark, 8.0)
    check("父进程死后守护决定重启", fired)
    if fired:
        print(f"  重启标记已写入：{mark.name}")
    try:
        guard.wait(timeout=8)
        check("重启后守护自行退出（交给新实例）", True)
    except subprocess.TimeoutExpired:
        guard.kill()
        check("重启后守护自行退出（交给新实例）", False, "守护未退出")


def case_graceful(root: Path) -> None:
    print("\n[2] 正常退出")
    victim = subprocess.Popen([PY, "-c", "import time; time.sleep(60)"])
    guard = start_guard(root, victim.pid)
    time.sleep(2.0)
    # 模拟「家长按密码退出」：主进程先写令牌再消失
    runtime = root / "data" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "exit.ok").write_text(str(int(time.time() * 1000)), encoding="utf-8")
    victim.kill()
    victim.wait(timeout=5)

    try:
        guard.wait(timeout=6)
        exited = True
    except subprocess.TimeoutExpired:
        guard.kill()
        exited = False
    check("收到令牌后守护退出", exited)
    check("没有误触发重启", not (runtime / "relaunch.dry").exists())


def case_no_password(root: Path) -> None:
    print("\n[3] 没设密码时不该拉起")
    victim = subprocess.Popen([PY, "-c", "import time; time.sleep(60)"])
    guard = start_guard(root, victim.pid)
    time.sleep(2.0)
    victim.kill()
    victim.wait(timeout=5)
    try:
        guard.wait(timeout=6)
    except subprocess.TimeoutExpired:
        guard.kill()
    check("无密码时放弃拉起", not (root / "data" / "runtime" / "relaunch.dry").exists())


def main() -> int:
    print("=" * 56)
    print("看门狗重启行为验证")
    print("=" * 56)
    case_killed(make_root(True))
    case_graceful(make_root(True))
    case_no_password(make_root(False))

    print("-" * 56)
    print(f"通过 {len(PASSED)} 项")
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for item in FAILED:
            print("  -", item)
        return 1
    print("看门狗行为符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
