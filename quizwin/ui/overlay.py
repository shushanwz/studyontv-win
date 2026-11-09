"""解锁后的悬浮计时条。

主窗口收起后，桌面上只留这一条：显示剩余时间，可拖动，点结束立刻回锁。
它不自己起定时器——每秒由 App 的锁屏心跳统一刷新，少一个可能跑飞的循环。
"""

from __future__ import annotations

import tkinter as tk

from .theme import Fonts, Palette, mix
from .widgets import Button, label

BAR_WIDTH = 236
BAR_HEIGHT = 64


class OverlayBar(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.theme: Palette = app.theme
        self.fonts: Fonts = app.fonts
        self._drag_offset = (0, 0)
        self._moved = False

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
        inner.pack(fill="both", expand=True, padx=14, pady=10)
        inner.bind("<ButtonPress-1>", self._on_press)
        inner.bind("<B1-Motion>", self._on_drag)
        inner.bind("<ButtonRelease-1>", self._on_release)

        self.dot = tk.Canvas(inner, width=10, height=10, bg=self.theme.surface, highlightthickness=0, bd=0)
        self.dot.pack(side="left", pady=(2, 0))
        self._dot_item = self.dot.create_oval(1, 1, 9, 9, fill=self.theme.ok, outline=self.theme.ok)

        texts = tk.Frame(inner, bg=self.theme.surface)
        texts.pack(side="left", padx=(10, 0))
        texts.bind("<ButtonPress-1>", self._on_press)
        texts.bind("<B1-Motion>", self._on_drag)
        self.caption = label(texts, self.theme, "剩余时间", font=self.fonts.tiny, fg=self.theme.text3)
        self.caption.pack(anchor="w")
        self.clock = label(texts, self.theme, "00:00", font=(self.fonts.family, 17, "bold"), fg=self.theme.text)
        self.clock.pack(anchor="w")
        for widget in (self.caption, self.clock):
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_drag)

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

    # ---------- 位置 ----------

    def _place_window(self) -> None:
        saved = self.app.parent.overlay_position()
        if saved:
            x, y = saved
        else:
            x = max(0, self.winfo_screenwidth() - BAR_WIDTH - 40)
            y = 56
        self.geometry(f"{BAR_WIDTH}x{BAR_HEIGHT}+{int(x)}+{int(y)}")

    def _on_press(self, event) -> None:
        self._drag_offset = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())
        self._moved = False

    def _on_drag(self, event) -> None:
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        max_x = self.winfo_screenwidth() - BAR_WIDTH
        max_y = self.winfo_screenheight() - BAR_HEIGHT
        x = max(0, min(max_x, x))
        y = max(0, min(max_y, y))
        self.geometry(f"+{x}+{y}")
        self._moved = True

    def _on_release(self, _event=None) -> None:
        if self._moved:
            self.app.parent.save_overlay_position(self.winfo_x(), self.winfo_y())
        self.lift()

    # ---------- 刷新 ----------

    def refresh(self, seconds: int) -> None:
        seconds = max(0, int(seconds))
        text = f"{seconds // 60:02d}:{seconds % 60:02d}"
        if seconds <= 10:
            color = self.theme.bad
            caption = "马上要回锁了"
        elif seconds <= 60:
            color = self.theme.accent
            caption = "快结束了"
        else:
            color = self.theme.text
            caption = "剩余时间"
        self.clock.configure(text=text, fg=color)
        self.caption.configure(text=caption)
        dot_color = self.theme.bad if seconds <= 60 else self.theme.ok
        self.dot.itemconfigure(self._dot_item, fill=dot_color, outline=dot_color)

    def keep_on_top(self) -> None:
        try:
            self.attributes("-topmost", True)
            self.lift()
        except tk.TclError:
            pass
