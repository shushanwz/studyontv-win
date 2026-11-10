"""解锁后的悬浮计时条。

主窗口收起后，桌面上只留这一条：显示剩余时间，可拖动，点结束立刻回锁。
它不自己起定时器——每秒由 App 的锁屏心跳统一刷新，少一个可能跑飞的循环。

两处与像素尺寸有关的坑，都记在这里免得以后又踩：
  * 窗口尺寸不能写死。字体是「磅」，会随系统缩放（125% / 150%）放大，而窗口
    尺寸是物理像素——写死 64 高时，放大后的「10:00」下半截会被窗口边框切掉，
    看起来就是「时间显示不全」。所以先量字再定窗口（见 _fit）。
  * 说明文字不要忽长忽短。几种状态的说明都保持四个汉字，窗口就不会一秒一变。
"""

from __future__ import annotations

import tkinter as tk

from .theme import Fonts, Palette, mix
from .widgets import Button, label

BAR_MIN_WIDTH = 236
BAR_MIN_HEIGHT = 64
PAD_X = 14
PAD_Y = 10

# 说明文字的四种状态，长度都控制在四个字（宽度不跳，布局不抖）
CAPTION_NORMAL = "剩余时间"
CAPTION_SOON = "快结束了"
CAPTION_SAVE = "记得保存"
CAPTION_LAST = "即将回锁"

BLINK_SECONDS = 30  # 最后 30 秒开始闪


class OverlayBar(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.theme: Palette = app.theme
        self.fonts: Fonts = app.fonts
        self._drag_offset = (0, 0)
        self._moved = False
        self._blink = False
        self._fitted = False
        self._size = (BAR_MIN_WIDTH, BAR_MIN_HEIGHT)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.theme.line)
        self._place_window()

        body = tk.Frame(self, bg=self.theme.surface)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        body.bind("<ButtonPress-1>", self._on_press)
        body.bind("<B1-Motion>", self._on_drag)
        body.bind("<ButtonRelease-1>", self._on_release)

        inner = tk.Frame(body, bg=self.theme.surface)
        inner.pack(fill="both", expand=True, padx=PAD_X, pady=PAD_Y)
        inner.bind("<ButtonPress-1>", self._on_press)
        inner.bind("<B1-Motion>", self._on_drag)
        inner.bind("<ButtonRelease-1>", self._on_release)
        self._inner = inner

        # 按钮先占右：pack 按调用顺序分空间，先给按钮定位，左边的文字再怎么变
        # 都不会把它挤出去
        Button(
            inner,
            self.theme,
            self.fonts,
            "结束",
            command=self.app.end_unlock_early,
            kind="quiet",
            height=30,
            padx=12,
        ).pack(side="right")

        self.dot = tk.Canvas(inner, width=10, height=10, bg=self.theme.surface, highlightthickness=0, bd=0)
        self.dot.pack(side="left", pady=(2, 0))
        self._dot_item = self.dot.create_oval(1, 1, 9, 9, fill=self.theme.ok, outline=self.theme.ok)

        texts = tk.Frame(inner, bg=self.theme.surface)
        texts.pack(side="left", padx=(10, 12))
        texts.bind("<ButtonPress-1>", self._on_press)
        texts.bind("<B1-Motion>", self._on_drag)
        self.caption = label(texts, self.theme, CAPTION_NORMAL, font=self.fonts.tiny, fg=self.theme.text3)
        self.caption.pack(anchor="w")
        self.clock = label(texts, self.theme, "00:00", font=(self.fonts.family, 17, "bold"), fg=self.theme.text)
        self.clock.pack(anchor="w")
        for widget in (self.caption, self.clock):
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_drag)

    # ---------- 尺寸 ----------

    def _fit(self, text: str, caption: str) -> None:
        """按当前字体尺寸把窗口定成「装得下」的大小。

        先塞进同位数的最宽数字（8 比 1 宽）与最长的说明，量出 inner 需要多大，
        再把窗口定成那个尺寸——100% 与 150% 缩放下都不会裁字。
        """
        self._fitted = True
        mask = "".join("8" if ch.isdigit() else ch for ch in text)
        widest_caption = max(
            (CAPTION_NORMAL, CAPTION_SOON, CAPTION_SAVE, CAPTION_LAST), key=lambda item: len(item)
        )
        self.clock.configure(text=mask)
        self.caption.configure(text=widest_caption)
        self.update_idletasks()
        width = max(BAR_MIN_WIDTH, self._inner.winfo_reqwidth() + PAD_X * 2 + 2)
        height = max(BAR_MIN_HEIGHT, self._inner.winfo_reqheight() + PAD_Y * 2 + 2)
        self._size = (width, height)
        self._place_window()
        self.clock.configure(text=text)
        self.caption.configure(text=caption)

    # ---------- 位置 ----------

    def _place_window(self) -> None:
        width, height = self._size
        saved = self.app.parent.overlay_position()
        if saved:
            x, y = saved
        else:
            x = max(0, self.winfo_screenwidth() - width - 40)
            y = 56
        x = max(0, min(max(0, self.winfo_screenwidth() - width), int(x)))
        y = max(0, min(max(0, self.winfo_screenheight() - height), int(y)))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_press(self, event) -> None:
        self._drag_offset = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())
        self._moved = False

    def _on_drag(self, event) -> None:
        width, height = self._size
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        max_x = self.winfo_screenwidth() - width
        max_y = self.winfo_screenheight() - height
        x = max(0, min(max_x, x))
        y = max(0, min(max_y, y))
        self.geometry(f"+{x}+{y}")
        self._moved = True

    def _on_release(self, _event=None) -> None:
        if self._moved:
            self.app.parent.save_overlay_position(self.winfo_x(), self.winfo_y())
        self.lift()

    # ---------- 刷新 ----------

    @staticmethod
    def _format(seconds: int) -> str:
        """一位数小时也能显示：超过 60 分钟写成 H:MM:SS。"""
        seconds = max(0, int(seconds))
        if seconds >= 3600:
            return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def refresh(self, seconds: int) -> None:
        seconds = max(0, int(seconds))
        text = self._format(seconds)

        if seconds <= 10:
            caption, color = CAPTION_LAST, self.theme.bad
        elif seconds <= BLINK_SECONDS:
            caption, color = CAPTION_SAVE, self.theme.bad
        elif seconds <= 60:
            caption, color = CAPTION_SOON, self.theme.accent
        else:
            caption, color = CAPTION_NORMAL, self.theme.text

        if not self._fitted:
            self._fit(text, caption)

        # 最后 30 秒：每秒翻一次，时钟与窗口描边一起闪，提醒先把视频/游戏存一下
        if seconds <= BLINK_SECONDS:
            self._blink = not self._blink
            border = self.theme.bad if self._blink else self.theme.line
            if not self._blink:
                color = self.theme.text3 if seconds <= 10 else self.theme.text2
        else:
            self._blink = False
            border = self.theme.line

        self.clock.configure(text=text, fg=color)
        self.caption.configure(text=caption, fg=self.theme.bad if seconds <= BLINK_SECONDS else self.theme.text3)
        try:
            self.configure(bg=border)
        except tk.TclError:
            return

        dot_color = self.theme.bad if seconds <= BLINK_SECONDS else self.theme.ok
        # 圆点跟着一起闪：灭的那一下用底色填充，看起来就是「闪」
        if seconds <= BLINK_SECONDS and not self._blink:
            dot_color = mix(self.theme.bad, self.theme.surface, 0.75)
        self.dot.itemconfigure(self._dot_item, fill=dot_color, outline=dot_color)

    def keep_on_top(self) -> None:
        try:
            self.attributes("-topmost", True)
            self.lift()
        except tk.TclError:
            pass
