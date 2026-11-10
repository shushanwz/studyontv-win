"""生成安装向导用的两张图（NSIS MUI2 要求 24 位 BMP）。

    build/welcome.bmp  164x314  欢迎页 / 完成页左侧竖图
    build/header.bmp   150x57   内页右上角小图

配色与程序一致：深底 #0A0A0C，强调 #FF8A3D。
用法：python tools/make_installer_art.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"

BG_TOP = (18, 18, 22)
BG_BOTTOM = (8, 8, 10)
ACCENT = (255, 138, 61)
TEXT = (240, 240, 244)
TEXT_DIM = (140, 140, 150)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise SystemExit("找不到中文字体。")


def gradient(width: int, height: int, scale: int = 3) -> Image.Image:
    image = Image.new("RGB", (width * scale, height * scale), BG_TOP)
    draw = ImageDraw.Draw(image)
    total = height * scale
    for y in range(total):
        ratio = y / max(1, total - 1)
        color = tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * ratio) for i in range(3)
        )
        draw.line([(0, y), (width * scale, y)], fill=color)
    return image


def draw_badge(image: Image.Image, x: int, y: int, size: int, glyph: int) -> None:
    """橙色圆角方块 + 白色「题」字。"""
    draw = ImageDraw.Draw(image)
    radius = int(size * 0.24)
    draw.rounded_rectangle((x, y, x + size, y + size), radius=radius, fill=ACCENT)
    f = font(glyph)
    draw.text((x + size / 2, y + size / 2 + glyph * 0.03), "题", font=f, fill=(20, 14, 10), anchor="mm")


def make_welcome() -> Path:
    width, height, scale = 164, 314, 3
    image = gradient(width, height, scale)
    draw = ImageDraw.Draw(image)

    box = width * scale
    badge_size = int(box * 0.42)
    draw_badge(image, (box - badge_size) // 2, int(height * scale * 0.22), badge_size, int(0.5 * badge_size))

    # 底部一条强调色细线，呼应程序里的下划线
    draw.rectangle(
        (int(box * 0.34), int(height * scale * 0.62), int(box * 0.66), int(height * scale * 0.62) + 6),
        fill=ACCENT,
    )

    f_title = font(int(box * 0.115))
    f_sub = font(int(box * 0.068))
    draw.text((box / 2, height * scale * 0.70), "题了个题", font=f_title, fill=TEXT, anchor="mm")
    draw.text((box / 2, height * scale * 0.775), "答题换时间", font=f_sub, fill=TEXT_DIM, anchor="mm")

    image = image.resize((width, height), Image.LANCZOS)
    path = BUILD / "welcome.bmp"
    image.save(path, "BMP")
    return path


def make_header() -> Path:
    width, height, scale = 150, 57, 4
    image = gradient(width, height, scale)
    badge_size = int(height * scale * 0.66)
    draw_badge(image, int(width * scale * 0.04), (height * scale - badge_size) // 2, badge_size, int(0.52 * badge_size))

    draw = ImageDraw.Draw(image)
    f = font(int(height * scale * 0.27))
    text_x = int(width * scale * 0.04) + badge_size + int(height * scale * 0.14)
    draw.text((text_x, height * scale * 0.5), "题了个题", font=f, fill=TEXT, anchor="lm")

    image = image.resize((width, height), Image.LANCZOS)
    path = BUILD / "header.bmp"
    image.save(path, "BMP")
    return path


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    for path in (make_welcome(), make_header()):
        print(f"已生成 {path}（{Image.open(path).size}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
