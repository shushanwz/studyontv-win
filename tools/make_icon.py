"""生成程序图标 build/app.ico（多尺寸）。

配色取自界面主题：深色底 #1C1C21，强调色 #FF8A3D。
用法：python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "app.ico"

BG = (28, 28, 33, 255)          # surface2
ACCENT = (255, 138, 61, 255)    # accent
GLYPH = "题"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",   # 微软雅黑 Bold
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",   # 黑体
    r"C:\Windows\Fonts\Deng.ttf",     # 等线
]


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise SystemExit("找不到可用的中文字体，请检查系统字体目录。")


def render(size: int) -> Image.Image:
    scale = 4  # 先大后缩，边缘更干净
    box = size * scale
    image = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = int(box * 0.22)
    draw.rounded_rectangle((0, 0, box - 1, box - 1), radius=radius, fill=BG)

    # 内描边：小尺寸下撑住轮廓
    stroke = max(2, int(box * 0.035))
    draw.rounded_rectangle(
        (stroke // 2, stroke // 2, box - 1 - stroke // 2, box - 1 - stroke // 2),
        radius=radius - stroke // 2,
        outline=ACCENT,
        width=stroke,
    )

    font = pick_font(int(box * 0.50))
    draw.text((box / 2, box / 2 + box * 0.015), GLYPH, font=font, fill=ACCENT, anchor="mm")

    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [256, 128, 64, 48, 32, 24, 16]
    frames = [render(s) for s in sizes]
    frames[0].save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"已生成 {OUT}（{', '.join(str(s) for s in sizes)}）")

    png = OUT.with_suffix(".png")
    render(256).save(png)
    print(f"预览图 {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
