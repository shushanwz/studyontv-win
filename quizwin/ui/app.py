"""主窗口：顶栏、导航、页面路由与全局状态。"""

from __future__ import annotations

import os
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from ..core.engine import Engine, EngineError
from ..core.lock import REASON_MANUAL, LockController
from ..core.parent import ParentControl
from ..core import paths
from ..core.storage import Storage
from ..winapi import HardenOptions, Hardening, Watchdog, set_task_manager_disabled
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
        # shell_mode 决定「当前长什么样」，lock_mode 决定「这个进程是不是锁屏进程」。
        # 两者分开，家长才能从锁屏临时切到设置界面再切回来。
        self.shell_mode = "lock" if self.lock_mode else "normal"
        # 锁屏进程但还没有密码 → 先走「首次设置」，设完直接进锁屏
        self.setup_required = bool(self.lock_mode)
        self.settings_mode = False
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
        # 已经有密码就不用再走设置向导
        self.setup_required = bool(self.lock_mode and not self.parent.has_password)
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

        self._guard_job = None
        self.hardening: Hardening | None = None
        self.watchdog: Watchdog | None = None
        self._quit_from_setup = False
        if self.lock_mode:
            self._apply_lock_window()
            self._build_guard()

        self.report_callback_exception = self._on_callback_error
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
        if self.setup_required:
            # 第一次运行（或上次没设完）：先强制设家长密码，设完立刻进锁屏。
            # 这段时间不装键盘钩子——密码还没设，装了也只是给家长添麻烦。
            self.after(120, self._run_first_setup)
        elif self.lock_mode:
            self.after(300, self._tick_lock)
            # 等窗口真正映射到桌面再装钩子：过早装，hwnd 还没成型
            self.after(600, self.engage_guard)

    # ------------------------------------------------------------ 锁屏形态

    def _apply_lock_window(self) -> None:
        """全屏无边框置顶。这是「锁屏」的窗口层，输入层与进程层由 winapi 负责。"""
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{screen_w}x{screen_h}+0+0")
        self.minsize(900, 640)

    # ------------------------------------------------------------ 系统层封锁

    def _data_dir(self) -> Path:
        """数据目录。启动早期（storage 还没建）出错时也能拿到一个合法路径。"""
        storage = getattr(self, "storage", None)
        return storage.data_dir if storage is not None else paths.default_data_dir()

    def _build_guard(self) -> None:
        if os.environ.get("QUIZWIN_NO_GUARD") == "1":
            # 自动化测试用：不装钩子、不起守护，避免测试进程真的把桌面锁住
            self.hardening = None
            self.watchdog = None
            return
        cfg = self.parent.cfg.get("hardening") or {}
        self.hardening = Hardening(
            lambda: self.winfo_id(),
            HardenOptions(
                keyboard_hook=bool(cfg.get("keyboardHook", True)),
                clip_cursor=bool(cfg.get("clipCursor", True)),
                keep_foreground=True,
            ),
        )
        self.watchdog = (
            Watchdog(self._data_dir().parent, exe_dir=paths.app_dir())
            if bool(cfg.get("watchdog", True))
            else None
        )

    def reload_guard_config(self) -> None:
        """设置里改了加固开关后，按新配置重建封锁对象。"""
        if not self.lock_mode or os.environ.get("QUIZWIN_NO_GUARD") == "1":
            return
        if self.hardening is not None:
            self.hardening.uninstall()
        if self.watchdog is not None:
            self.watchdog.stop(graceful=False)
        self._build_guard()

    def engage_guard(self) -> None:
        """进入锁屏：装键盘钩子、限制鼠标、拉起看门狗。"""
        if not self.lock_mode:
            return
        # 启动时那次 engage 是延迟调度的，若期间已经解锁（家长手快，或自动解锁），
        # 再装上就等于把刚放行的人又关回去。以此状态为准。
        if self.lock.is_unlocked() or self.settings_mode:
            return
        if self.hardening is not None:
            if self.hardening.install():
                self.hardening.keep_foreground()
            else:
                # 钩子没装上，锁屏就只剩一个全屏窗口，必须让家长知道
                self.toast(f"输入封锁未生效：{self.hardening.last_error}", 8000)
        if self.watchdog is not None and not self.watchdog.running:
            self.watchdog.start()
        cfg = self.parent.cfg.get("hardening") or {}
        if cfg.get("disableTaskMgr"):
            if set_task_manager_disabled(True):
                self._mark_taskmgr()
        else:
            self._restore_taskmgr()

    def _taskmgr_mark(self) -> Path:
        return self._data_dir() / "runtime" / "taskmgr.flag"

    def _mark_taskmgr(self) -> None:
        """留个记号：这个策略是本程序设的，退出时要自己收拾干净。"""
        try:
            path = self._taskmgr_mark()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("1", encoding="utf-8")
        except OSError:
            pass

    def _restore_taskmgr(self) -> None:
        """只清自己设过的策略，别人设的不碰。"""
        path = self._taskmgr_mark()
        if not path.exists():
            return
        set_task_manager_disabled(False)
        try:
            path.unlink()
        except OSError:
            pass

    def release_guard(self, graceful: bool = False) -> None:
        """离开锁屏：卸载钩子、放开鼠标。

        graceful=True 表示这是家长放行的正常退出，要让看门狗别再拉起来；
        解锁自由玩电脑时只能 graceful=False，否则计时归零回锁后看门狗会误判退出。
        """
        if self.hardening is not None:
            self.hardening.uninstall()
        if self.watchdog is not None:
            self.watchdog.stop(graceful=graceful)
        if graceful:
            self._restore_taskmgr()


    # ------------------------------------------------------------ 骨架

    def _build_shell(self) -> None:
        if self.shell_mode == "lock":
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
        if self.lock_mode:
            # 家长从锁屏进了设置，总得有条路回去
            Button(right, theme, fonts, "返回锁屏", self.back_to_lock, kind="ghost", height=32).pack(
                side="right", padx=(0, 12)
            )

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

        if self.shell_mode == "lock":
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
            if self.shell_mode == "lock":
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

    def switch_shell(self, mode: str, page: str | None = None) -> None:
        """在「锁屏形态」与「普通形态」之间整体重建界面。

        不切换窗口属性（overrideredirect 反复开关会闪、也会打乱 DPI 与焦点），
        只换内容：锁屏是全屏无边框 + 只有答题页，普通形态带导航。
        """
        target = "normal" if str(mode).lower() == "normal" else "lock"
        wanted = page or self.current
        self._cancel_overlay_job()
        if self._toast_job:
            try:
                self.after_cancel(self._toast_job)
            except tk.TclError:
                pass
            self._toast_job = None
        # 只属于某个形态的控件，重建前先置空：
        # 否则切回锁屏后 self.status_pill 还指着已销毁的控件，一刷新就抛 TclError
        for name in ("status_pill", "clock_label", "day_label", "header"):
            setattr(self, name, None)
        for child in list(self.children.values()):
            child.destroy()
        self.shell_mode = target
        self._nav_tabs = {}
        self.pages = {}
        self.lock_bar = None
        self.current = wanted if wanted else "quiz"
        self._build_shell()
        self._build_pages()
        self.set_page(self.current if self.current in self.pages else "quiz")
        try:
            self._paint_clock()
        except tk.TclError:
            pass
        apply_dark_title_bar(self, self.theme.name == "dark" and target == "normal")

    def open_settings_as_parent(self) -> None:
        """家长验证通过 → 进设置。放开输入封锁，但不算解锁，也不消耗额度。"""
        self.release_guard(graceful=False)
        self.settings_mode = True
        self.switch_shell("normal", "rules")
        self.attributes("-topmost", True)

    def back_to_lock(self) -> None:
        """从设置回锁屏：重建锁屏形态并重新装上封锁。"""
        self.settings_mode = False
        self.switch_shell("lock", "quiz")
        page = self.pages.get("quiz")
        if page is not None:
            page.refresh_entry()
        self.engage_guard()
        self.lift()

    def refresh_status(self) -> None:
        pill = getattr(self, "status_pill", None)
        if pill is None or not pill.winfo_exists():
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
        """解锁：收起锁屏窗口，桌面上只留一条计时。

        必须先卸掉输入封锁——晚一秒，家长就多一秒用不了自己的电脑。
        """
        self.release_guard(graceful=False)
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
        self.engage_guard()
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

    # ------------------------------------------------------------ 首次设置

    def _run_first_setup(self) -> None:
        """第一次运行：没密码就先强制设一个，设完立刻进锁屏。

        三条底线：
          * 不能跳过——跳过就等于留下一个可以自由玩的窗口；
          * 不设就退出程序，桌面原样还回去，家长下次再来设；
          * 这一步自己出错也退出，绝不停在「没锁住又能用」的中间态。
        """
        if not self.setup_required:
            return
        self.setup_required = False
        try:
            if self.parent.has_password:
                self.enter_lock_now()
                return
            passed, _code = ParentSetupDialog.ask(self, self, fullscreen=True)
            if not passed:
                self.quit_from_setup()
                return
            self.enter_lock_now()
            self.toast("家长密码已设置，答够时长就能解锁电脑", 4000)
        except Exception:  # noqa: BLE001 - 首次设置失败必须兜住，不能半开着
            detail = traceback.format_exc()
            try:
                log_path = self._data_dir() / "error.log"
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n[首次设置失败]\n{detail}\n")
            except OSError:
                pass
            self.quit_from_setup()

    def enter_lock_now(self) -> None:
        """从「首次设置」直接进入锁屏，不必重启程序。

        窗口在 __init__ 里就已经是全屏无边框了，这里补上内容形态与系统层封锁。
        """
        self.lock_mode = True
        self.settings_mode = False
        self.lock.force_lock(REASON_MANUAL)
        self.switch_shell("lock", "quiz")
        self._apply_lock_window()
        page = self.pages.get("quiz")
        if page is not None:
            page.refresh_entry()
        self.lift()
        self.engage_guard()
        self._tick_lock()

    def quit_from_setup(self) -> None:
        """首次设置取消：直接退出，绝不停在可用状态。"""
        self.setup_required = False
        self._quit_from_setup = True
        # 让对话框先把自己销毁干净，再关主窗口，避免回调踩到已销毁的控件
        self.after(1, lambda: self.on_close(force=True))

    def _tick_lock(self) -> None:
        """锁屏期间的每秒心跳：既判断是否到点，也顺带刷新额度条。"""
        self._lock_tick_job = None
        self._lock_ticks = getattr(self, "_lock_ticks", 0) + 1
        if self.settings_mode:
            # 家长在设置里，不要抢焦点、也不要因为计时把人踢回锁屏
            self._lock_tick_job = self.after(1000, self._tick_lock)
            return
        try:
            # 每两秒把窗口顶回最前一次：偷换前台窗口是绕过锁屏最常见的一步
            if self.hardening is not None and self._lock_ticks % 2 == 1:
                self.hardening.pump()
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
            self._paint_clock()
        except tk.TclError:
            # 控件正在被重建（切换形态、换主题），这一拍跳过，但排程必须继续，
            # 否则时钟一停就再也不走了
            pass
        self.after(20_000, self._tick_clock)

    def _paint_clock(self) -> None:
        now = datetime.now()
        clock = getattr(self, "clock_label", None)
        if clock is not None and clock.winfo_exists():
            clock.configure(text=now.strftime("%H:%M"))
        day = getattr(self, "day_label", None)
        if day is not None and day.winfo_exists():
            weekday = "一二三四五六日"[now.weekday()]
            day.configure(text=now.strftime("%m 月 %d 日 · 周") + weekday)

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
        # 先让看门狗知道「这次是正常退出」，再卸载钩子，最后才销毁窗口
        self.release_guard(graceful=True)
        try:
            if self.engine:
                self.engine.st.save_state()
                if self.engine.bank and self.engine.bank.dirty:
                    self.engine.bank.save()
        finally:
            self.destroy()

    # ------------------------------------------------------------ 异常

    def _on_callback_error(self, exc_type, exc_value, exc_tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            log_path = self._data_dir() / "error.log"
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
