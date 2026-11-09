"""自绘控件：圆角按钮、选项卡片、开关、胶囊标签、滚动容器。

tkinter 原生控件在深色主题下观感很差，这里用 Canvas 自绘关键控件，
保证与上游电视端的视觉语言一致（圆角、描边聚焦、大字号）。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from .theme import Fonts, Palette, mix, round_rect, wrap_text


def _parent_bg(widget: tk.Misc, fallback: str) -> str:
    try:
        value = widget.cget("bg")
        if value:
            return str(value)
    except tk.TclError:
        pass
    return fallback


class Button(tk.Canvas):
    """圆角按钮。kind: primary / ghost / danger / quiet。"""

    def __init__(
        self,
        master: tk.Misc,
        theme: Palette,
        fonts: Fonts,
        text: str,
        command: Callable[[], None] | None = None,
        kind: str = "ghost",
        width: int | None = None,
        height: int = 42,
        font=None,
        padx: int = 22,
        parent_bg: str | None = None,
        radius: int = 12,
        enabled: bool = True,
    ):
        self.theme = theme
        self.fonts = fonts
        self.parent_bg = parent_bg or _parent_bg(master, theme.bg)
        self.label = text
        self.kind = kind
        self.command = command
        self.font = font or fonts.body_bold
        self.radius = radius
        self.enabled = enabled
        self.hover = False
        self.pressed = False
        measured = fonts.measure(master, text, self.font)
        calc_width = max(84, measured + padx * 2)
        super().__init__(
            master,
            width=width or calc_width,
            height=height,
            bg=self.parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2" if enabled else "arrow",
        )
        self._fixed_width = width is not None
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda _event: self._draw())
        self._draw()

    # ---------------- 状态 ----------------

    def set_text(self, text: str) -> None:
        self.label = text
        if not self._fixed_width:
            measured = self.fonts.measure(self, text, self.font)
            self.configure(width=max(84, measured + 44))
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def _on_enter(self, _event=None):
        if not self.enabled:
            return
        self.hover = True
        self._draw()

    def _on_leave(self, _event=None):
        self.hover = False
        self.pressed = False
        self._draw()

    def _on_press(self, _event=None):
        if not self.enabled:
            return
        self.pressed = True
        self._draw()

    def _on_release(self, _event=None):
        if not self.enabled:
            return
        was_pressed = self.pressed
        self.pressed = False
        self._draw()
        if was_pressed and self.command:
            self.command()

    # ---------------- 绘制 ----------------

    def _colors(self) -> tuple[str, str, str]:
        """返回 (填充色, 文字色, 描边色)。"""
        theme = self.theme
        if not self.enabled:
            if self.kind == "primary":
                return mix(theme.surface2, theme.bg, 0.35), theme.text3, ""
            return theme.surface, theme.text3, theme.line

        if self.kind == "primary":
            fill = mix(theme.accent, "#FFFFFF", 0.14) if self.hover else theme.accent
            if self.pressed:
                fill = mix(theme.accent, "#000000", 0.12)
            text = "#0A0A0C" if theme.name == "dark" else "#FFFFFF"
            return fill, text, ""

        if self.kind == "danger":
            fill = theme.bad_soft if not self.hover else mix(theme.bad_soft, theme.bad, 0.16)
            return fill, theme.bad, mix(theme.bad, theme.bg, 0.45)

        if self.kind == "quiet":
            return (theme.surface2 if self.hover else self.parent_bg), theme.text2, ""

        # ghost
        fill = theme.surface2 if self.hover else theme.surface
        if self.pressed:
            fill = theme.surface3
        return fill, theme.text, theme.line

    def _draw(self) -> None:
        self.delete("all")
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        fill, text_color, outline = self._colors()
        offset = 1 if (self.pressed and self.enabled) else 0
        round_rect(
            self,
            1,
            1 + offset,
            width - 1,
            height - 1 + offset,
            self.radius,
            fill=fill,
            outline=outline or fill,
            width=1,
        )
        self.create_text(
            width / 2,
            height / 2 + offset,
            text=self.label,
            fill=text_color,
            font=self.font,
        )


class OptionCard(tk.Canvas):
    """答题选项卡片：左侧字母徽标 + 右侧文本，支持聚焦 / 选中 / 对错着色。"""

    STATE_NORMAL = "normal"
    STATE_FOCUS = "focus"
    STATE_SELECTED = "selected"
    STATE_RIGHT = "right"
    STATE_WRONG = "wrong"
    STATE_DIM = "dim"

    def __init__(
        self,
        master: tk.Misc,
        theme: Palette,
        fonts: Fonts,
        letter: str,
        text: str,
        state: str = STATE_NORMAL,
        compact: bool = False,
        on_click: Callable[[], None] | None = None,
        parent_bg: str | None = None,
    ):
        self.theme = theme
        self.fonts = fonts
        self.letter = letter
        self.text = text
        self.state = state
        self.compact = compact
        self.on_click = on_click
        self.parent_bg = parent_bg or _parent_bg(master, theme.bg)
        body_font = fonts.option_small if compact else fonts.option
        super().__init__(
            master,
            bg=self.parent_bg,
            highlightthickness=0,
            bd=0,
            height=self.preferred_height(),
            cursor="hand2" if on_click else "arrow",
        )
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_click)

    # ---------------- 尺寸 ----------------

    def _body_font(self):
        return self.fonts.option_small if self.compact else self.fonts.option

    def preferred_height(self) -> int:
        """初始高度（实际高度由 grid 统一指定，绘制时按真实宽度折行）。"""
        return 52 if self.compact else 78

    def set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        self._draw()

    # ---------------- 事件 ----------------

    def _on_enter(self, _event=None):
        if self.on_click and self.state in (self.STATE_NORMAL, self.STATE_FOCUS):
            self.set_state(self.STATE_FOCUS)

    def _on_leave(self, _event=None):
        if self.state == self.STATE_FOCUS and self.on_click:
            self.state = self.STATE_NORMAL
            self._draw()

    def _on_click(self, _event=None):
        if self.on_click:
            self.on_click()

    # ---------------- 绘制 ----------------

    def _draw(self) -> None:
        self.delete("all")
        theme = self.theme
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())

        fill = theme.surface2
        outline = theme.line
        text_color = theme.text
        letter_fill = theme.surface3
        letter_color = theme.text2
        badge_check = False

        if self.state == self.STATE_FOCUS:
            fill = mix(theme.surface2, theme.focus, 0.08)
            outline = theme.focus
            letter_fill = mix(theme.surface3, theme.focus, 0.18)
            letter_color = theme.text
        elif self.state == self.STATE_SELECTED:
            fill = theme.accent_soft
            outline = theme.accent
            letter_fill = theme.accent
            letter_color = "#0A0A0C" if theme.name == "dark" else "#FFFFFF"
            badge_check = True
        elif self.state == self.STATE_RIGHT:
            fill = theme.ok_soft
            outline = theme.ok
            letter_fill = theme.ok
            letter_color = "#0A0A0C" if theme.name == "dark" else "#FFFFFF"
            badge_check = True
        elif self.state == self.STATE_WRONG:
            fill = theme.bad_soft
            outline = theme.bad
            letter_fill = theme.bad
            letter_color = "#0A0A0C" if theme.name == "dark" else "#FFFFFF"
        elif self.state == self.STATE_DIM:
            fill = theme.surface
            outline = theme.line
            text_color = theme.text3
            letter_color = theme.text3

        round_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            14,
            fill=fill,
            outline=outline or fill,
            width=2 if self.state in (self.STATE_FOCUS, self.STATE_SELECTED, self.STATE_RIGHT, self.STATE_WRONG) else 1,
        )

        badge_size = 26
        badge_x = 18
        badge_y = (height - badge_size) / 2
        round_rect(
            self,
            badge_x,
            badge_y,
            badge_x + badge_size,
            badge_y + badge_size,
            8,
            fill=letter_fill,
            outline=letter_fill,
        )
        self.create_text(
            badge_x + badge_size / 2,
            badge_y + badge_size / 2,
            text="✓" if badge_check and self.state in (self.STATE_RIGHT, self.STATE_SELECTED) else self.letter,
            fill=letter_color,
            font=(self.fonts.family, 10, "bold"),
        )

        font = self._body_font()
        text_left = badge_x + badge_size + 16
        available = width - text_left - 20
        tk_font = tkfont.Font(root=self, font=font)
        lines = wrap_text(self.text or "", tk_font, int(available))
        if self.compact:
            lines = lines[:1]
        else:
            lines = lines[:3]
        line_height = tk_font.metrics("linespace")
        total = len(lines) * line_height
        start_y = (height - total) / 2 + line_height / 2
        for index, line in enumerate(lines):
            self.create_text(text_left, start_y + index * line_height, text=line, fill=text_color, font=font, anchor="w")


class Switch(tk.Canvas):
    """开关控件。"""

    def __init__(
        self,
        master: tk.Misc,
        theme: Palette,
        checked: bool = False,
        on_change: Callable[[bool], None] | None = None,
        width: int = 46,
        height: int = 26,
        parent_bg: str | None = None,
    ):
        self.theme = theme
        self.checked = bool(checked)
        self.on_change = on_change
        super().__init__(
            master,
            width=width,
            height=height,
            bg=parent_bg or _parent_bg(master, theme.bg),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.bind("<ButtonRelease-1>", self._toggle)
        self.bind("<Configure>", lambda _event: self._draw())
        self._draw()

    def _toggle(self, _event=None):
        self.checked = not self.checked
        self._draw()
        if self.on_change:
            self.on_change(self.checked)

    def set(self, checked: bool) -> None:
        self.checked = bool(checked)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        theme = self.theme
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        track = theme.accent if self.checked else theme.surface3
        round_rect(self, 1, 1, width - 1, height - 1, height / 2, fill=track, outline=track)
        radius = height / 2 - 4
        center_x = (width - radius - 4) if self.checked else (radius + 4)
        center_y = height / 2
        knob = "#FFFFFF" if self.checked else theme.text3
        self.create_oval(
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
            fill=knob,
            outline=knob,
        )


class Pill(tk.Canvas):
    """胶囊状态标签。"""

    def __init__(
        self,
        master: tk.Misc,
        theme: Palette,
        fonts: Fonts,
        text: str = "",
        parent_bg: str | None = None,
        height: int = 30,
        accent: bool = False,
    ):
        self.theme = theme
        self.fonts = fonts
        self.label = text
        self.accent = accent
        super().__init__(
            master,
            height=height,
            bg=parent_bg or _parent_bg(master, theme.bg),
            highlightthickness=0,
            bd=0,
        )
        self.bind("<Configure>", lambda _event: self._draw())
        self.set_text(text)

    def set_text(self, text: str) -> None:
        self.label = text
        measured = self.fonts.measure(self, text, self.fonts.small)
        self.configure(width=max(60, measured + 30))
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        theme = self.theme
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        fill = theme.accent_soft if self.accent else theme.surface2
        outline = mix(theme.accent, theme.bg, 0.5) if self.accent else theme.line
        text_color = theme.accent if self.accent else theme.text2
        round_rect(self, 1, 1, width - 1, height - 1, height / 2, fill=fill, outline=outline)
        self.create_text(width / 2, height / 2, text=self.label, fill=text_color, font=self.fonts.small)


class RoundPanel(tk.Frame):
    """按内容自适应的圆角卡片：把控件放进 self.body 即可。"""

    def __init__(
        self,
        master: tk.Misc,
        theme: Palette,
        radius: int = 20,
        padding: int = 24,
        parent_bg: str | None = None,
        fill: str | None = None,
    ):
        background = parent_bg or _parent_bg(master, theme.bg)
        super().__init__(master, bg=background, bd=0, highlightthickness=0)
        self.theme = theme
        self.radius = radius
        self.fill = fill or theme.surface
        self._canvas = tk.Canvas(self, bg=background, highlightthickness=0, bd=0)
        self._canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self.body = tk.Frame(self, bg=self.fill)
        self.body.pack(padx=padding, pady=padding)
        self.bind("<Configure>", self._draw)

    def _draw(self, event=None) -> None:
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 4 or height < 4:
            return
        self._canvas.delete("panel")
        round_rect(
            self._canvas,
            1,
            1,
            width - 1,
            height - 1,
            self.radius,
            fill=self.fill,
            outline=self.theme.line,
            width=1,
            tags="panel",
        )


class SlimScrollbar(tk.Canvas):
    """自绘细滚动条：原生 Scrollbar 在深色主题里永远是白底灰箭头，很扎眼。"""

    WIDTH = 10
    PAD = 2

    def __init__(self, master: tk.Misc, theme: Palette, command=None, parent_bg: str | None = None, width: int = 10):
        bg = parent_bg or _parent_bg(master, theme.bg)
        super().__init__(master, width=width, bg=bg, highlightthickness=0, bd=0, takefocus=0)
        self.theme = theme
        self.command = command
        self.bg = bg
        self.first = 0.0
        self.last = 1.0
        self._drag_origin = None
        self._drag_first = 0.0
        self._hover = False
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    # --- 与 tk.Scrollbar 兼容的接口 -------------------------------------

    def set(self, first, last) -> None:
        first, last = float(first), float(last)
        if abs(first - self.first) < 1e-4 and abs(last - self.last) < 1e-4:
            return
        self.first, self.last = first, last
        self._draw()

    def get(self):
        return (self.first, self.last)

    # --- 绘制与交互 -----------------------------------------------------

    def _draw(self) -> None:
        self.delete("all")
        theme = self.theme
        height = max(2, self.winfo_height())
        width = max(2, self.winfo_width())
        span = max(0.02, self.last - self.first)
        top = self.PAD + (height - 2 * self.PAD) * self.first
        bottom = top + (height - 2 * self.PAD) * span
        bottom = min(bottom, height - self.PAD)
        if bottom - top < 24:
            bottom = min(height - self.PAD, top + 24)
            top = max(self.PAD, bottom - 24)
        fill = mix(theme.text2, self.bg, 0.35) if self._hover else mix(theme.text2, self.bg, 0.62)
        round_rect(self, 2, top, width - 2, bottom, (width - 4) / 2, fill=fill, outline="")

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._draw()

    def _fraction(self, y: float) -> float:
        usable = max(1, self.winfo_height() - 2 * self.PAD)
        return (y - self.PAD) / usable

    def _on_press(self, event) -> None:
        if not self.command:
            return
        frac = self._fraction(event.y)
        if self.first <= frac <= self.last:
            self._drag_origin = event.y
            self._drag_first = self.first
        else:
            # 点击空白处：直接跳到该位置
            self.command("moveto", max(0.0, min(1.0, frac - (self.last - self.first) / 2)))

    def _on_drag(self, event) -> None:
        if self._drag_origin is None or not self.command:
            return
        usable = max(1, self.winfo_height() - 2 * self.PAD)
        delta = (event.y - self._drag_origin) / usable
        self.command("moveto", max(0.0, min(1.0, self._drag_first + delta)))

    def _on_release(self, _event=None) -> None:
        self._drag_origin = None


class ScrollFrame(tk.Frame):
    """带细滚动条的滚动容器，内容放在 self.body 里。"""

    def __init__(self, master: tk.Misc, theme: Palette, parent_bg: str | None = None):
        self.theme = theme
        bg = parent_bg or _parent_bg(master, theme.bg)
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar = SlimScrollbar(self, theme, command=self.canvas.yview, parent_bg=bg)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _on_body_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, _event=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _event=None):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event):
        if self.canvas.winfo_height() >= self.body.winfo_reqheight():
            return
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0)


def divider(master: tk.Misc, theme: Palette) -> tk.Frame:
    frame = tk.Frame(master, bg=theme.line, height=1)
    return frame


def label(
    master: tk.Misc,
    theme: Palette,
    text: str,
    font=None,
    fg: str | None = None,
    bg: str | None = None,
    wraplength: int = 0,
    justify: str = "left",
    anchor: str = "w",
):
    return tk.Label(
        master,
        text=text,
        font=font or theme_fonts(master),
        fg=fg or theme.text,
        bg=bg or _parent_bg(master, theme.bg),
        wraplength=wraplength,
        justify=justify,
        anchor=anchor,
        bd=0,
    )


_DEFAULT_FONT_CACHE: dict[int, Fonts] = {}


def bind_fonts(widget: tk.Misc, fonts: Fonts) -> None:
    _DEFAULT_FONT_CACHE[id(widget)] = fonts


def theme_fonts(widget: tk.Misc):
    root = widget.winfo_toplevel()
    return _DEFAULT_FONT_CACHE.get(id(root), ("Microsoft YaHei UI", 12))
