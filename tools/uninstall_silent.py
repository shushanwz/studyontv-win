"""静默卸载已安装的程序（验证卸载流程用）。

为什么不能直接用 `uninstall.exe /S`：
    Git Bash（MSYS）会把 `/S` 当成路径转换成 `S:\\`，卸载器收到的是垃圾参数，
    于是静默模式不生效、进程立刻返回，看起来像「卸载没反应」。
    用 Python 的 subprocess 直接 CreateProcess，参数原样传过去。

用法：
    python tools\\uninstall_silent.py              # 卸默认安装位置
    python tools\\uninstall_silent.py 别的安装目录
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / "题了个题"


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_install_dir()
    uninstaller = target / "uninstall.exe"
    if not uninstaller.exists():
        print(f"没找到卸载器：{uninstaller}")
        return 1

    # state.json 存在时，卸载器会弹「是否删除数据」的询问框，静默模式下会卡住。
    # 跑自动化前先把它挪开，测完再挪回去。
    state = Path(os.environ.get("LOCALAPPDATA", "")) / "题了个题" / "data" / "state.json"
    print(f"调用：{uninstaller} /S")
    proc = subprocess.run([str(uninstaller), "/S"], capture_output=True, text=True)
    print(f"返回码：{proc.returncode}")
    time.sleep(8)

    print("目录仍在" if target.exists() else "目录已删除")
    if state.exists():
        print("注意：数据目录里的 state.json 还在（卸载时选了保留，或询问被跳过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
