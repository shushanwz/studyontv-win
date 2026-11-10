"""抓任意窗口的截图（不依赖窗口是否在最前面）。

打包后的 exe 没有 tkinter 句柄可用，只能按标题找窗口，
所以这里不接 widget，而是枚举顶层窗口按标题匹配。

用法：
    python tools\\window_shot.py 输出.png [标题关键词]
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from winshot import capture  # noqa: E402

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def find_window(keyword: str) -> int:
    """按标题关键词找面积最大的可见顶层窗口。"""
    found: list[tuple[int, int, int, str]] = []

    def callback(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if keyword in buf.value and user32.IsWindowVisible(hwnd):
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((hwnd, rect.right - rect.left, rect.bottom - rect.top, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    if not found:
        return 0
    found.sort(key=lambda item: item[1] * item[2], reverse=True)
    hwnd, width, height, title = found[0]
    print(f"窗口：{title!r} {width}x{height} hwnd={hwnd}")
    return hwnd


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python tools\\window_shot.py 输出.png [标题关键词]")
        return 1
    out = Path(sys.argv[1])
    keyword = sys.argv[2] if len(sys.argv) > 2 else "题了个题"
    hwnd = find_window(keyword)
    if not hwnd:
        print("没找到窗口")
        return 1

    bmp = capture(hwnd, out.with_suffix(".bmp"))
    from PIL import Image

    Image.open(bmp).save(out)
    bmp.unlink(missing_ok=True)
    print(f"已保存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
