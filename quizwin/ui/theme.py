"""配色、字体与绘图辅助。

视觉参考上游电视端的深色方案（#08080A 背景、米白文字、橙色强调、卡片描边聚焦），
并额外提供浅色主题，供白天在电脑上使用。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface2: str
    surface3: str
    line: str
    text: str
    text2: str
    text3: str
    accent: str
    accent_soft: str
    ok: str
    ok_soft: str
    bad: str
    bad_soft: str
    focus: str
    shadow: str


DARK = Palette(
    name="dark",
    bg="#08080A",
    surface="#131316",
    surface2="#1C1C21",
    surface3="#26262C",
    line="#2E2E36",
    text="#F2F2F4",
    text2="#A0A0A8",
    text3="#6E6E76",
    accent="#FF8A3D",
    accent_soft="#2A1B12",
    ok="#7BC294",
    ok_soft="#16241B",
    bad="#E5766F",
    bad_soft="#2A1717",
    focus="#E5E5E5",
    shadow="#000000",
)

LIGHT = Palette(
    name="light",
    bg="#F2F2F5",
    surface="#FFFFFF",
    surface2="#F7F7FA",
    surface3="#ECECF1",
    line="#DCDCE3",
    text="#1B1B20",
    text2="#5A5A64",
    text3="#8A8A94",
    accent="#D95F12",
    accent_soft="#FDEEE3",
    ok="#2F8A4E",
    ok_soft="#E8F5EC",
    bad="#C0392B",
    bad_soft="#FBEAE8",
    focus="#1B1B20",
    shadow="#C9C9D2",
)


def palette(name: str) -> Palette:
    return LIGHT if str(name).lower() == "light" else DARK


class Fonts:
    """字体族探测 + 字号阶梯。"""

    def __init__(self, root: tk.Misc):
        families = set(tkfont.families(root))
        chosen = "TkDefaultFont"
        for candidate in (
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "PingFang SC",
            "SimHei",
        ):
            if candidate in families:
                chosen = candidate
                break
        self.family = chosen
        self.h1 = (chosen, 26, "bold")
        self.h2 = (chosen, 19, "bold")
        self.h3 = (chosen, 15, "bold")
        self.body = (chosen, 12)
        self.body_bold = (chosen, 12, "bold")
        self.small = (chosen, 10)
        self.tiny = (chosen, 9)
        self.question = (chosen, 26, "bold")
        self.question_long = (chosen, 21, "bold")
        self.option = (chosen, 16)
        self.option_small = (chosen, 14)
        self.counter = (chosen, 22, "bold")
        self.mono = ("Consolas", 11)

    def measure(self, root: tk.Misc, text: str, font) -> int:
        return tkfont.Font(root=root, font=font).measure(text)


def round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs):
    """在 Canvas 上画圆角矩形（用平滑多边形近似，Windows 下边缘足够平滑）。"""
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    if radius <= 0:
        return canvas.create_rectangle(x1, y1, x2, y2, **kwargs)

    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


def apply_dark_title_bar(window: tk.Misc, dark: bool) -> None:
    """让 Windows 原生标题栏跟随深色 / 浅色主题（Win10 1809+）。"""
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
    except Exception:
        pass


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """按比例混合两个 #RRGGBB 颜色，ratio=0 取 a，1 取 b。"""
    ratio = max(0.0, min(1.0, ratio))
    a = color_a.lstrip("#")
    b = color_b.lstrip("#")
    if len(a) != 6 or len(b) != 6:
        return color_a
    out = []
    for index in range(3):
        va = int(a[index * 2:index * 2 + 2], 16)
        vb = int(b[index * 2:index * 2 + 2], 16)
        out.append(f"{int(round(va + (vb - va) * ratio)):02X}")
    return "#" + "".join(out)


HEAD_BAN = "，。、；：？！）】》」』”’…～—"
_WORD_CHARS = "._-/%'"


def _tail_chunk(prev: str) -> int:
    """prev 末尾最后一个「词」有多长：英文词整段搬，汉字一次一个。"""
    index = len(prev)
    while index > 0 and prev[index - 1].isascii() and (prev[index - 1].isalnum() or prev[index - 1] in _WORD_CHARS):
        index -= 1
    return len(prev) - index or 1


def _balance_tail(lines: list[str], font: tkfont.Font, width: int) -> None:
    """末行只剩一两个字时，从上一行匀字下来。

    逐字折行很容易折出「…点「」/「导入」。」这种孤字行。匀几个字下来，
    整体矩形更好看；只在末行明显偏短时动手，正常结尾不受影响。
    """
    if len(lines) < 2 or width <= 0:
        return
    last, prev = lines[-1], lines[-2]
    if not last.strip() or not prev.strip():
        return
    for _ in range(40):
        if not prev or font.measure(last) >= width * 0.4:
            break
        size = _tail_chunk(prev)
        while size > 1 and font.measure(prev[-size:] + last) > width:
            size -= 1
        last = prev[-size:] + last
        prev = prev[:-size]
        # 别把标点甩到行首：连带上一个字一起挪
        while prev and prev[-1] in HEAD_BAN:
            last = prev[-1] + last
            prev = prev[:-1]
    lines[-1], lines[-2] = last, prev


def wrap_text(text: str, font: tkfont.Font, width: int) -> list[str]:
    """按像素宽度折行，兼顾中英文（中文逐字断行，英文按空格断词）。

    折完会把末行调匀（见 _balance_tail），并把不留在行首的标点挪到上一行。
    """
    if width <= 0:
        return [text]
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        trial = current + char
        if font.measure(trial) <= width or not current:
            current = trial
        else:
            # 英文单词尽量不拆开
            if char.isascii() and char not in " ,.;:!?" and " " in current:
                head, _, tail = current.rpartition(" ")
                if head:
                    lines.append(head)
                    current = tail + char
                    continue
            if char in HEAD_BAN and len(current) > 1:
                lines.append(current[:-1])
                current = current[-1] + char
                continue
            lines.append(current)
            current = char
    if current or not lines:
        lines.append(current)
    _balance_tail(lines, font, width)
    return lines
