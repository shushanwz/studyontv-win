"""往当前前台窗口送按键 / 点鼠标，用于验证只能靠人手点一次的流程（首次设置、安装向导）。

注意：本脚本的进程不是 DPI 感知的，Windows 会把坐标按缩放比虚拟化。
截图里的物理像素坐标要先除以缩放比（125% 就除 1.25）再传进来。

用法：
    python tools\keypad.py type abc123456
    python tools\keypad.py key TAB ENTER
    python tools\keypad.py click 902 557
"""

from __future__ import annotations

import ctypes
import sys
import time

user32 = ctypes.windll.user32

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


def _send(items: list[INPUT]) -> None:
    array = (INPUT * len(items))(*items)
    user32.SendInput(len(items), array, ctypes.sizeof(INPUT))
    time.sleep(0.03)


def type_text(text: str) -> None:
    for ch in text:
        code = ord(ch)
        down = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)))
        up = INPUT(
            type=INPUT_KEYBOARD,
            union=_INPUTUNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)),
        )
        _send([down, up])


def press(vk: int) -> None:
    down = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(ki=KEYBDINPUT(vk, 0, 0, 0, None)))
    up = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)))
    _send([down, up])


def click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # 左键按下
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # 左键抬起


VK = {"TAB": 0x09, "ENTER": 0x0D, "ESC": 0x1B, "SPACE": 0x20, "BACK": 0x08}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    action = sys.argv[1]
    if action == "type":
        type_text(" ".join(sys.argv[2:]))
    elif action == "key":
        for name in sys.argv[2:]:
            press(VK[name.upper()])
            time.sleep(0.12)
    elif action == "click":
        click(int(sys.argv[2]), int(sys.argv[3]))
    else:
        print("未知动作", action)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
