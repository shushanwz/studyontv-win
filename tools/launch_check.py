"""启动验证：真实双击启动脚本 → 找到窗口 → 截图 → 正常关闭。

用法： python tools/launch_check.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from run import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()  # 不做 DPI 感知的话 GetWindowRect 拿到的是缩放后的逻辑坐标，截图会被裁

from winshot import capture  # noqa: E402

user32 = ctypes.windll.user32
TITLE_KEYWORD = "题了个题"


def find_window() -> int:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if TITLE_KEYWORD in buffer.value:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else 0


def main() -> int:
    print("启动 启动.bat …")
    subprocess.Popen(["cmd", "/c", "启动.bat"], cwd=str(ROOT), shell=False)

    hwnd = 0
    deadline = time.time() + 25
    while time.time() < deadline:
        hwnd = find_window()
        if hwnd:
            break
        time.sleep(0.5)

    if not hwnd:
        print("失败：25 秒内没有找到程序窗口")
        return 1

    print("已找到窗口，句柄", hwnd)
    time.sleep(2.0)
    out = ROOT / "shots" / "90-launch.bmp"
    out.parent.mkdir(parents=True, exist_ok=True)
    capture(hwnd, out)
    print("已截图：", out)

    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    for _ in range(20):
        time.sleep(0.3)
        if not user32.IsWindow(hwnd):
            print("窗口已正常关闭")
            return 0
    print("窗口 6 秒内没有关闭，可能有问题")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
