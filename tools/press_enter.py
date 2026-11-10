"""给指定窗口发一次回车 —— 用来推进安装向导翻页并逐页截图。

用法：
    python tools\\press_enter.py 安装

为什么不用自动化 UI 框架：NSIS 向导的按钮句柄不稳定，
而「下一步」「完成」都是默认按钮（带蓝色边框），发 WM_KEYDOWN 回车最省事。
"""

from __future__ import annotations

import ctypes
import sys
import time

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def find_window(keyword: str) -> int:
    found: list[int] = []

    def callback(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if keyword in buf.value and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else 0


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python tools\\press_enter.py 窗口标题关键词")
        return 1
    hwnd = find_window(sys.argv[1])
    if not hwnd:
        print("没找到窗口")
        return 1
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    user32.keybd_event(0x0D, 0, 0, 0)
    user32.keybd_event(0x0D, 0, 2, 0)
    print("已发送回车")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
