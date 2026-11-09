"""用 Windows PrintWindow 直接抓窗口内容，不依赖桌面是否可见。

比 CopyFromScreen 可靠：窗口被遮挡或远程会话下也能拿到内容。
"""

from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def window_handle(widget) -> int:
    widget.update_idletasks()
    hwnd = widget.winfo_id()
    parent = user32.GetParent(hwnd)
    return parent or hwnd


def capture(hwnd: int, path: Path) -> Path:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError("窗口尺寸无效")

    hdc = user32.GetDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    # PW_RENDERFULLCONTENT = 2，能抓到部分硬件加速与分层窗口的内容
    user32.PrintWindow(hwnd, mem_dc, 2)
    print(f"[shot] window rect {width}x{height}")

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = height
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0
    buffer_size = width * height * 4
    buffer = ctypes.create_string_buffer(buffer_size)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hdc)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(b"BM")
        handle.write(struct.pack("<IHHI", 54 + buffer_size, 0, 0, 54))
        handle.write(
            struct.pack(
                "<IiiHHIIiiII",
                40,
                width,
                height,
                1,
                32,
                0,
                buffer_size,
                2835,
                2835,
                0,
                0,
            )
        )
        handle.write(buffer.raw)
    return path
