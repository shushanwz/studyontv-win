"""主窗口：顶栏、导航、页面路由与全局状态。"""

from __future__ import annotations

import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from ..core.engine import Engine, EngineError
from ..core.lock import REASON_MANUAL, LockController
from ..core.parent import ParentControl
from ..core.storage import Storage
from .overlay import OverlayBar
from .page_lock import LockBar, ParentMenu, ParentSetupDialog, PasswordDialog
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
    def __init__(self, lock_mode: bool = False):
        super().__init__()
        self.withdraw()
        self.lock_mode = bool(lock_mode)
        self.title(APP_TITLE)
        width, height = 1280, 840
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(1080, 720)

        self.storage = Storage()
        self.parent = ParentControl(self.storage)
        self.lock = LockController(self.storage)
        # 上次若停在「已解锁」，这里一律收回：不信任跨进程的解锁状态
        self.lock_info = self.lock.recover_from_crash()
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
        self._overlay_job = None
        self.overlay = None
        self.lock_bar = None
        self._lock_tick_job = None
        self.pages: dict[str, tk.Frame] = {}
        self.current = "quiz"
        self._nav_tabs: dict[str, NavTab] = {}

        if self.lock_mode:
            self._apply_lock_window()

        self.report_callback_exception = self._report_exception
        self._build_shell()
        self._build_pages()
        self.set_page("quiz")
        self.bind_all("<Key>", self.dispatch_key)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self._tick_clock)
        if not self.lock_mode:
            self.after(30, lambda: apply_dark_title_bar(self, self.theme.name == "dark"))
        self.deiconify()
        self.lift()
        self.after(400, self._heartbeat)
        if self.lock_mode:
            self.after(300, self._tick_lock)

    # ------------------------------------------------------------ 锁屏形态

    def _apply_lock_window(self) -> None:
        """全屏无边框置顶。这是「锁屏」的窗口层，输入层与进程层由 winlock 负责。"""
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{screen_w}x{screen_h}+0+0")
        self.minsize(900, 640)


    # ------------------------------------------------------------ 骨架

    def _build_shell(self) -> None:
        if self.lock_mode:
            self._build_lock_shell()
        else:
            self._build_normal_shell()

    def _build_lock_shell(self) -> None:
        """锁屏形态：顶栏只留时间，底部是额度条，中间全是题。"""
        theme = self.theme
        fonts = self.fonts

        head = tk.Frame(self, bg=theme.bg, height=88)
        head.pack(side="top", fill="x")
        head.pack_propagate(False)

        left = tk.Frame(head, bg=theme.bg)
        left.pack(side="left", padx=(46, 0))
        logo = tk.Canvas(left, width=30, height=30, bg=theme.bg, highlightthickness=0, bd=0)
        logo.pack(side="left")
        round_rect(logo, 0, 0, 30, 30, 9, fill=theme.accent, outline=theme.accent)
        logo.create_polygon(11, 9, 11, 21, 21, 15, fill=theme.bg, outline=theme.bg)
        tk.Label(left, text="题了个题", bg=theme.bg, fg=theme.text, font=(fonts.family, 15, "bold")).pack(
            side="left", padx=(10, 0)
        )
        tk.Label(left, text="答够时长才能解锁电脑", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(
            side="left", padx=(16, 0)
        )

        right = tk.Frame(head, bg=theme.bg)
        right.pack(side="right", padx=(0, 46))
        self.clock_label = tk.Label(right, text="", bg=theme.bg, fg=theme.text2, font=(fonts.family, 20, "bold"))
        self.clock_label.pack(side="right")
        self.day_label = tk.Label(right, text="", bg=theme.bg, fg=theme.text3, font=fonts.small)
        self.day_label.pack(side="right", padx=(0, 14))

        tk.Frame(self, bg=theme.line, height=1).pack(side="top", fill="x")

        self.lock_bar = LockBar(self, self)
        self.lock_bar.pack(side="bottom", fill="x")

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

    def _build_normal_shell(self) -> None:
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

        if self.lock_mode:
            # 锁屏下只有答题页，导航栏都不建，孩子没有可去的别处
            page = QuizPage(self.body, self)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages["quiz"] = page
            return

        for key, cls in (("quiz", QuizPage), ("bank", BankPage), ("rules", RulesPage), ("about", AboutPage)):
            page = cls(self.body, self)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page

    # ------------------------------------------------------------ 路由

    def set_page(self, key: str) -> None:
        if key not in self.pages:
            if self.lock_mode:
                # 锁屏下没有别的页，强行跳转只当成一次提示
                self.toast("现在只能答题，要进设置得先让家长验证密码")
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
        pill = getattr(self, "status_pill", None)
        if pill is None:
            # 锁屏形态没有状态胶囊，进度改由底部额度条表达
            if self.lock_bar is not None:
                self.lock_bar.refresh()
            for page in self.pages.values():
                hook = getattr(page, "on_status_changed", None)
                if hook:
                    hook()
            return
        if not self.engine:
            pill.set_text("题库缺失")
            return
        try:
            pill.set_text(self.engine.status_text())
        except Exception:  # pragma: no cover - 状态异常不应阻塞界面
            pill.set_text("状态异常")
        for page in self.pages.values():
            hook = getattr(page, "on_status_changed", None)
            if hook:
                hook()

    # ------------------------------------------------------------ 家长控制

    def request_unlock(self, minutes: int) -> None:
        """点档位按钮：扣余额、开始倒计时、收起主窗口。"""
        if not self.engine:
            self.toast("题库缺失，无法兑换")
            return
        result = self.engine.redeem(minutes)
        if not result.get("ok"):
            if result.get("reason") == "quota":
                self.toast("今天的额度已经用完")
            else:
                self.toast(f"还差 {result.get('short', minutes)} 分钟")
            if self.lock_bar:
                self.lock_bar.refresh()
            return
        self.lock.unlock(minutes, source="answer")
        self.enter_overlay()

    def enter_overlay(self) -> None:
        """解锁：收起锁屏窗口，桌面上只留一条计时。"""
        if self.overlay is None:
            self.overlay = OverlayBar(self)
        self.overlay.refresh(self.lock.remaining_seconds())
        self.overlay.deiconify()
        self.overlay.keep_on_top()
        self.withdraw()
        self._cancel_overlay_job()
        self._overlay_job = self.after(600, self._tick_overlay)

    def _tick_overlay(self) -> None:
        self._overlay_job = None
        if self.overlay is None:
            return
        if self.lock.tick():
            self.return_to_lock()
            return
        self.overlay.refresh(self.lock.remaining_seconds())
        self.overlay.keep_on_top()
        self._overlay_job = self.after(1000, self._tick_overlay)

    def _cancel_overlay_job(self) -> None:
        if self._overlay_job:
            try:
                self.after_cancel(self._overlay_job)
            except tk.TclError:
                pass
            self._overlay_job = None

    def return_to_lock(self) -> None:
        """回到全屏锁屏：销毁计时条、拉起窗口、刷新答题入口。"""
        self._cancel_overlay_job()
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
        self.deiconify()
        self.attributes("-topmost", True)
        self.lift()
        page = self.pages.get("quiz")
        if page is not None:
            page.refresh_entry()
        if self.lock_bar:
            self.lock_bar.refresh()

    def end_unlock_early(self) -> None:
        self.lock.force_lock(REASON_MANUAL)
        self.return_to_lock()

    def open_parent_gate(self) -> None:
        """家长入口：先验密码，再给操作菜单。"""
        if not self.parent.has_password:
            self.start_parent_setup()
            return
        passed, new_code = PasswordDialog.ask(self, self, "家长解锁", "验证后可以临时解锁、退出程序或进入设置")
        if not passed:
            return
        ParentMenu(self, self, new_code)

    def parent_unlock(self, minutes: int | None = None, until_tomorrow: bool = False) -> None:
        if until_tomorrow:
            self.lock.unlock_until_tomorrow("parent")
        elif minutes:
            self.lock.unlock(minutes, "parent")
        self.enter_overlay()

    def start_parent_setup(self) -> bool:
        passed, _code = ParentSetupDialog.ask(self, self)
        if passed:
            self.toast("家长密码已设置，下次启动会先锁屏")
            if self.lock_bar:
                self.lock_bar.refresh()
        return passed

    def _tick_lock(self) -> None:
        """锁屏期间的每秒心跳：既判断是否到点，也顺带刷新额度条。"""
        self._lock_tick_job = None
        self._lock_ticks = getattr(self, "_lock_ticks", 0) + 1
        try:
            if self.lock.tick():
                self.return_to_lock()
            elif self.lock_bar and self.lock.is_locked() and self._lock_ticks % 3 == 0:
                self.lock_bar.refresh()
        except tk.TclError:
            return
        if self.lock.is_locked():
            self._lock_tick_job = self.after(1000, self._tick_lock)

    def _heartbeat(self) -> None:
        try:
            tamper = self.lock.heartbeat()
            if tamper and (self.lock_mode or self.overlay is not None):
                self.return_to_lock()
                self.toast("检测到系统时间被调整，已重新锁定")
        except tk.TclError:
            return
        self.after(10_000, self._heartbeat)

    def _maybe_setup_parent(self) -> None:
        """首次运行且没设密码：先问要不要启用家长控制。"""
        if self.lock_mode:
            return
        if self.parent.has_password or not self.parent.enabled:
            return
        self.start_parent_setup()

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
            now = datetime.now()
            self.clock_label.configure(text=now.strftime("%H:%M"))
            day_label = getattr(self, "day_label", None)
            if day_label is not None:
                weekday = "一二三四五六日"[now.weekday()]
                day_label.configure(text=now.strftime("%m 月 %d 日 · 周") + weekday)
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

    def on_close(self, force: bool = False) -> None:
        if self.lock_mode and not force:
            passed, _code = PasswordDialog.ask(
                self, self, "退出程序", "退出后电脑就不再受限制，需要家长密码才能退出"
            )
            if not passed:
                return
            self.lock.force_lock(REASON_MANUAL)
        self._cancel_overlay_job()
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
        if getattr(self, "lock_mode", False):
            # 锁屏时绝不能弹模态框：孩子点掉「确定」就等于拿到桌面，
            # 而且模态框会把整个界面卡住。日志照写，只在窗口内提示一下。
            try:
                self.toast(f"界面出了点问题，已记录：{exc_value}", 4000)
            except Exception:
                pass
            return
        messagebox.showerror("出错了", f"{exc_value}\n\n详细信息已写入 data/error.log", parent=self)
