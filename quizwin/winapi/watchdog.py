"""看门狗：主进程被强行结束后，把锁屏拉回来。

单进程挡不住任务管理器里的「结束任务」——这是程序层的天花板。
能做的只是把代价从「杀了就能玩」抬高到「杀了白等三秒，锁屏又回来了」。

约定：
- 主进程正常退出（家长密码放行）会写 `data/runtime/exit.ok`，守护看到令牌即收工；
- 没有令牌而父进程消失，判定为「被杀」，重新拉起锁屏；
- 连续拉起超过上限就放弃，避免留下一个不停开进程的僵尸。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x0102
PROCESS_TERMINATE = 0x0001
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000

INTERVAL = 2.0
EXIT_TOKEN_TTL = 90.0  # 秒；正常退出令牌的有效期
MAX_RELAUNCH = 5

TOKEN_NAME = "exit.ok"
PID_NAME = "watchdog.pid"


# ---------------------------------------------------------------- 进程工具


def _k32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def pid_alive(pid: int) -> bool:
    if not IS_WINDOWS or pid <= 0:
        return False
    k32 = _k32()
    handle = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        return k32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        k32.CloseHandle(handle)


def kill_pid(pid: int) -> bool:
    if not IS_WINDOWS or pid <= 0:
        return False
    k32 = _k32()
    handle = k32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return False
    try:
        return bool(k32.TerminateProcess(handle, 1))
    finally:
        k32.CloseHandle(handle)


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def pythonw() -> str:
    """优先用无控制台的解释器，避免拉起时闪黑框。打包后就是程序自身。"""
    exe = Path(sys.executable)
    if frozen():
        return str(exe)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


# ---------------------------------------------------------------- 令牌


def runtime_dir(root: Path) -> Path:
    path = root / "data" / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_exit_token(root: Path) -> None:
    """告诉守护进程：这次退出是家长放行的，不要拉回来。"""
    try:
        token = runtime_dir(root) / TOKEN_NAME
        token.write_text(str(int(time.time() * 1000)), encoding="utf-8")
    except OSError:
        pass


def token_fresh(root: Path, now: float | None = None) -> bool:
    """令牌是否仍然有效。过期令牌不算数，避免上次的残留挡住这次守护。"""
    path = root / "data" / "runtime" / TOKEN_NAME
    if not path.exists():
        return False
    try:
        stamp = int(path.read_text(encoding="utf-8").strip() or 0) / 1000.0
    except (OSError, ValueError):
        return False
    now = time.time() if now is None else now
    return 0 < now - stamp <= EXIT_TOKEN_TTL


def consume_exit_token(root: Path) -> None:
    try:
        (root / "data" / "runtime" / TOKEN_NAME).unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- 重启决策


def should_relaunch(root: Path) -> tuple[bool, str]:
    """父进程消失后要不要拉起。返回 (是否拉起, 原因)。"""
    if token_fresh(root):
        return False, "已收到正常退出令牌"
    state_path = root / "data" / "state.json"
    if not state_path.exists():
        return False, "缺少状态文件"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "状态文件不可读"
    if not isinstance(state, dict):
        return False, "状态文件格式异常"
    parent = state.get("parent") or {}
    if not isinstance(parent, dict) or not parent.get("enabled"):
        return False, "家长控制未启用"
    if not parent.get("password"):
        return False, "尚未设置家长密码"
    return True, "家长控制生效中"


# ---------------------------------------------------------------- 守护进程


def run_guard(
    root: Path,
    parent_pid: int,
    max_relaunch: int = MAX_RELAUNCH,
    exe_dir: Path | None = None,
) -> int:
    """守护循环。父进程消失时拉起锁屏，然后自己退出（新进程会起新的守护）。"""
    relaunched = 0
    while True:
        if token_fresh(root):
            consume_exit_token(root)
            _clear_pid(root)
            return 0
        if not pid_alive(parent_pid):
            ok, reason = should_relaunch(root)
            if not ok or relaunched >= max_relaunch:
                _clear_pid(root)
                return 0
            _spawn_lock(root, exe_dir)
            relaunched += 1
            _clear_pid(root)
            return 0
        time.sleep(INTERVAL)


def _spawn_lock(root: Path, exe_dir: Path | None = None) -> None:
    if os.environ.get("QUIZWIN_GUARD_DRY") == "1":
        # 自检模式：只留痕、不真拉起。验证「父进程被杀后守护会重启锁屏」
        # 这件事本身，又不会在别人正用电脑时把桌面锁住。
        try:
            (runtime_dir(root) / "relaunch.dry").write_text(str(int(time.time() * 1000)), encoding="utf-8")
        except OSError:
            pass
        return
    if frozen():
        # 打包后没有 run.py，直接再拉起自己
        cmd = [sys.executable, "--force-lock"]
        cwd = str(exe_dir or Path(sys.executable).resolve().parent)
    else:
        base = Path(exe_dir) if exe_dir else root
        cmd = [pythonw(), str(base / "run.py"), "--force-lock"]
        cwd = str(base)
    try:
        subprocess.Popen(
            cmd,
            cwd=cwd,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _clear_pid(root: Path) -> None:
    try:
        (root / "data" / "runtime" / PID_NAME).unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- 客户端


class Watchdog:
    """主进程这一侧的开关：起守护、停守护。"""

    def __init__(self, root: Path, exe_dir: Path | None = None):
        self.root = Path(root)
        self.exe_dir = Path(exe_dir) if exe_dir else self.root
        self.proc: subprocess.Popen | None = None
        self.pid = 0
        self.last_error = ""

    @property
    def running(self) -> bool:
        return bool(self.pid and pid_alive(self.pid))

    def start(self) -> bool:
        if not IS_WINDOWS:
            self.last_error = "非 Windows 系统，看门狗不可用"
            return False
        if self.running:
            return True
        self._kill_stale()
        if frozen():
            # 打包后由程序自身带 --guard 参数进入守护模式
            guard_cmd = [sys.executable, "--guard"]
        else:
            guard_cmd = [pythonw(), str(self.exe_dir / "quizwin" / "winapi" / "watchdog.py"), "--guard"]
        guard_cmd += ["--root", str(self.root), "--parent-pid", str(os.getpid()), "--exe-dir", str(self.exe_dir)]
        try:
            self.proc = subprocess.Popen(
                guard_cmd,
                cwd=str(self.exe_dir),
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.last_error = f"看门狗启动失败：{exc}"
            return False
        self.pid = int(self.proc.pid or 0)
        try:
            runtime_dir(self.root)
            (self.root / "data" / "runtime" / PID_NAME).write_text(str(self.pid), encoding="utf-8")
        except OSError:
            pass
        return True

    def stop(self, graceful: bool = True) -> None:
        """停止守护。graceful=True 表示这次是家长放行的正常退出，不要再拉起来。"""
        if graceful:
            write_exit_token(self.root)
        if self.pid:
            kill_pid(self.pid)
        if self.proc is not None:
            try:
                self.proc.wait(timeout=1.5)
            except Exception:
                pass
        self.proc = None
        self.pid = 0
        _clear_pid(self.root)

    def _kill_stale(self) -> None:
        """清掉上一个实例留下的守护，避免越积越多。"""
        path = self.root / "data" / "runtime" / PID_NAME
        if not path.exists():
            return
        try:
            pid = int(path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid and pid != os.getpid() and pid_alive(pid):
            kill_pid(pid)
        _clear_pid(self.root)


# ---------------------------------------------------------------- 入口


def main(argv: list[str]) -> int:
    if "--guard" not in argv:
        print("看门狗由主程序启动，不单独运行。")
        return 0
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else Path.cwd()
    pid = int(argv[argv.index("--parent-pid") + 1]) if "--parent-pid" in argv else 0
    exe_dir = Path(argv[argv.index("--exe-dir") + 1]) if "--exe-dir" in argv else None
    return run_guard(root, pid, exe_dir=exe_dir)


if __name__ == "__main__":  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main(sys.argv[1:]))
