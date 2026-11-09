"""主窗口：顶栏、导航、页面路由与全局状态。"""

from __future__ import annotations

import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from ..core.engine import Engine, EngineError
from ..core.storage import Storage
from .theme import DARK, LIGHT, Fonts, apply_dark_title_bar, palette
from .widgets import Button, Pill, bind_fonts, round_rect

APP_TITLE = "题了个题 · 桌面版"
NAV_ITEMS = (
    ("quiz", "答题"),
    ("bank", "题库"),
    ("rules", "规则"),
    ("about", "关于"),
)


class NavTab(tk.Canvas):
    def __init__(self, master, app: "App", key: str, text: str):
        self.app = app
        self.key = key
        self.label = text
        self.active = False
        self.hover = False
        super().__init__(
            master,
            height=72,
            width=len(text) * 20 + 36,
            bg=app.theme.bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.bind("<ButtonRelease-1>", lambda _e: app.set_page(key))
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Configure>", lambda _e: self.draw())

    def _enter(self, _event=None):
        self.hover = True
        self.draw()

    def _leave(self, _event=None):
        self.hover = False
        self.draw()

    def set_active(self, active: bool) -> None:
        self.active = active
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        theme = self.app.theme
        fonts = self.app.fonts
        width = self.winfo_width() or int(self["width"])
        height = self.winfo_height() or 72
        color = theme.text if self.active else (theme.text2 if not self.hover else theme.text)
        self.create_text(width / 2, height / 2 - 4, text=self.label, fill=color, font=fonts.h3)
        if self.active:
            self.create_rectangle(width / 2 - 12, height - 12, width / 2 + 12, height - 9, fill=theme.accent, outline="")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title(APP_TITLE)
        width, height = 1280, 840
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(1080, 720)

        self.storage = Storage()
        try:
            self.engine = Engine(self.storage)
            self.engine_error = ""
        except EngineError as exc:
            self.engine = None
            self.engine_error = str(exc)

        self.theme = palette(self.storage.state.get("theme", "dark"))
        self.fonts = Fonts(self)
        bind_fonts(self, self.fonts)

        self.configure(bg=self.theme.bg)
        self._toast_job = None
        self.pages: dict[str, tk.Frame] = {}
        self.current = "quiz"
        self._nav_tabs: dict[str, NavTab] = {}

        self.report_callback_exception = self._report_exception
        self._build_shell()
        self._build_pages()
        self.set_page("quiz")
        self.bind_all("<Key>", self.dispatch_key)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self._tick_clock)
        self.after(30, lambda: apply_dark_title_bar(self, self.theme.name == "dark"))
        self.deiconify()
        self.lift()

    # ------------------------------------------------------------ 骨架

    def _build_shell(self) -> None:
        theme = self.theme
        fonts = self.fonts

        self.header = tk.Frame(self, bg=theme.bg, height=78)
        self.header.pack(side="top", fill="x")
        self.header.pack_propagate(False)

        brand = tk.Frame(self.header, bg=theme.bg)
        brand.pack(side="left", padx=(36, 42))
        logo = tk.Canvas(brand, width=34, height=34, bg=theme.bg, highlightthickness=0, bd=0)
        logo.pack(side="left", pady=(0, 0))
        round_rect(logo, 0, 0, 34, 34, 10, fill=theme.accent, outline=theme.accent)
        logo.create_polygon(13, 10, 13, 24, 24, 17, fill=theme.bg, outline=theme.bg)
        brand_text = tk.Label(brand, text="题了个题", bg=theme.bg, fg=theme.text, font=(fonts.family, 16, "bold"))
        brand_text.pack(side="left", padx=(12, 0))

        nav = tk.Frame(self.header, bg=theme.bg)
        nav.pack(side="left")
        for key, label in NAV_ITEMS:
            tab = NavTab(nav, self, key, label)
            tab.pack(side="left", padx=(0, 6))
            self._nav_tabs[key] = tab

        right = tk.Frame(self.header, bg=theme.bg)
        right.pack(side="right", padx=(0, 36))
        self.clock_label = tk.Label(right, text="", bg=theme.bg, fg=theme.text3, font=(fonts.family, 11))
        self.clock_label.pack(side="right", padx=(16, 0))
        self.status_pill = Pill(right, theme, fonts, "正在加载…", parent_bg=theme.bg)
        self.status_pill.pack(side="right")

        tk.Frame(self, bg=theme.line, height=1).pack(side="top", fill="x")

        self.body = tk.Frame(self, bg=theme.bg)
        self.body.pack(side="top", fill="both", expand=True)

        self.toast_label = tk.Label(
            self,
            text="",
            bg=theme.surface3,
            fg=theme.text,
            font=(fonts.family, 11),
            padx=18,
            pady=9,
        )

    def _build_pages(self) -> None:
        from .page_about import AboutPage
        from .page_bank import BankPage
        from .page_quiz import QuizPage
        from .page_rules import RulesPage

        for key, cls in (("quiz", QuizPage), ("bank", BankPage), ("rules", RulesPage), ("about", AboutPage)):
            page = cls(self.body, self)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page

    # ------------------------------------------------------------ 路由

    def set_page(self, key: str) -> None:
        if key not in self.pages:
            return
        previous = self.pages.get(self.current)
        if previous is not None and previous is not self.pages.get(key):
            hook = getattr(previous, "on_hide", None)
            if hook:
                hook()
        self.current = key
        for name, tab in self._nav_tabs.items():
            tab.set_active(name == key)
        page = self.pages[key]
        page.tkraise()
        page.on_show()
        self.refresh_status()

    def refresh_status(self) -> None:
        if not self.engine:
            self.status_pill.set_text("题库缺失")
            return
        try:
            self.status_pill.set_text(self.engine.status_text())
        except Exception:  # pragma: no cover - 状态异常不应阻塞界面
            self.status_pill.set_text("状态异常")
        for page in self.pages.values():
            hook = getattr(page, "on_status_changed", None)
            if hook:
                hook()

    # ------------------------------------------------------------ 通知

    def toast(self, text: str, ms: int = 2400) -> None:
        theme = self.theme
        self.toast_label.configure(text=text, bg=theme.surface3, fg=theme.text)
        self.toast_label.place(relx=0.5, rely=1.0, anchor="s", y=-26)
        self.toast_label.lift()
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(ms, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast_job = None
        self.toast_label.place_forget()

    def alert(self, title: str, message: str) -> None:
        messagebox.showinfo(title, message, parent=self)

    def confirm(self, title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message, parent=self))

    # ------------------------------------------------------------ 主题

    def apply_theme(self, name: str) -> None:
        """切换深色 / 浅色：重建界面，保留当前页面。"""
        target = "light" if str(name).lower() == "light" else "dark"
        if target == self.theme.name:
            return
        self.storage.state["theme"] = target
        self.storage.save_state()
        current = self.current
        for child in list(self.children.values()):
            child.destroy()
        self.theme = LIGHT if target == "light" else DARK
        self.configure(bg=self.theme.bg)
        self._nav_tabs = {}
        self.pages = {}
        self._build_shell()
        self._build_pages()
        self.set_page(current)
        apply_dark_title_bar(self, target == "dark")
        self.toast("已切换为" + ("浅色" if target == "light" else "深色") + "主题")

    # ------------------------------------------------------------ 时钟

    def _tick_clock(self) -> None:
        try:
            self.clock_label.configure(text=datetime.now().strftime("%H:%M"))
        except tk.TclError:
            return
        self.after(20_000, self._tick_clock)

    # ------------------------------------------------------------ 键盘

    def dispatch_key(self, event) -> str | None:
        page = self.pages.get(self.current)
        handler = getattr(page, "handle_key", None)
        if handler and handler(event):
            return "break"
        return None

    # ------------------------------------------------------------ 退出

    def on_close(self) -> None:
        try:
            if self.engine:
                self.engine.st.save_state()
                if self.engine.bank and self.engine.bank.dirty:
                    self.engine.bank.save()
        finally:
            self.destroy()

    # ------------------------------------------------------------ 异常

    def _report_exception(self, exc_type, exc_value, exc_tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            log_path = Path(__file__).resolve().parents[2] / "data" / "error.log"
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n{detail}\n")
        except OSError:
            pass
        messagebox.showerror("出错了", f"{exc_value}\n\n详细信息已写入 data/error.log", parent=self)
