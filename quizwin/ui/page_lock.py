"""锁屏界面组件：额度条、密码对话框、首次设置向导。

锁屏整体由 App 以全屏形态承载（见 app.py 的 lock_mode），这里只提供三块：
  * LockBar          —— 常驻底部，显示余额、进度与四档兑换按钮
  * PasswordDialog   —— 模态密码框，含冷却倒计时与恢复码重设
  * ParentSetupDialog —— 首次运行的密码设置向导，强制抄写恢复码
"""

from __future__ import annotations

import tkinter as tk

from .theme import Fonts, Palette, apply_dark_title_bar, mix, round_rect
from .widgets import Button, label


def _center(window: tk.Toplevel, width: int, height: int) -> None:
    parent = window.master.winfo_toplevel()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
    except tk.TclError:
        px = py = 0
        pw, ph = window.winfo_screenwidth(), window.winfo_screenheight()
    x = px + max(0, (pw - width) // 2)
    y = py + max(0, (ph - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


class _Entry(tk.Frame):
    """带描边的输入框：tk.Entry 本身在深色主题下不容易改边框。"""

    def __init__(self, master, theme: Palette, fonts: Fonts, show: str = "", width: int = 22):
        super().__init__(master, bg=theme.surface2, highlightbackground=theme.line, highlightthickness=1)
        self.entry = tk.Entry(
            self,
            show=show,
            font=(fonts.family, 15),
            bg=theme.surface2,
            fg=theme.text,
            insertbackground=theme.text,
            relief="flat",
            bd=0,
            width=width,
            highlightthickness=0,
        )
        self.entry.pack(fill="x", padx=12, pady=9)
        self.entry.bind("<FocusIn>", lambda _e: self.configure(highlightbackground=theme.accent))
        self.entry.bind("<FocusOut>", lambda _e: self.configure(highlightbackground=theme.line))

    def get(self) -> str:
        return self.entry.get()

    def clear(self) -> None:
        self.entry.delete(0, "end")

    def focus(self) -> None:
        try:
            if self.entry.winfo_exists():
                self.entry.focus_set()
        except tk.TclError:
            pass


class _DialogBase(tk.Toplevel):
    """对话框基类：延迟回调统一登记，销毁时一并取消。

    tkinter 的 after 不随窗口销毁失效，回调再去碰控件就是
    「bad window path name」——真机上已经踩到过一次。
    """

    def __init__(self, parent):
        super().__init__(parent)
        self._jobs: list[str] = []

    def later(self, delay: int, callback):
        job = self.after(delay, callback)
        self._jobs.append(job)
        return job

    def focus_later(self, widget, delay: int = 60) -> None:
        def run():
            try:
                if self.winfo_exists() and widget.winfo_exists():
                    widget.focus()
            except tk.TclError:
                pass

        self.later(delay, run)

    def dark_title_later(self) -> None:
        """DWM 属性要在原生窗口真正创建后才生效，所以多试几次而不是只试一回。"""

        def apply(attempt: int = 0) -> None:
            if not self.winfo_exists():
                return
            apply_dark_title_bar(self, self.theme.name == "dark")
            if attempt < 2:
                self.later(140, lambda: apply(attempt + 1))

        self.later(60, apply)

    def _drop_job(self, job) -> None:
        try:
            self.after_cancel(job)
        except (tk.TclError, ValueError):
            pass

    def destroy(self) -> None:
        for job in list(self._jobs):
            self._drop_job(job)
        self._jobs.clear()
        cooldown = getattr(self, "_cooldown_job", None)
        if cooldown:
            self._drop_job(cooldown)
            self._cooldown_job = None
        super().destroy()


class PasswordDialog(_DialogBase):
    """模态密码框。用完读 self.result。"""

    def __init__(self, parent, app, title: str = "家长密码", hint: str = ""):
        super().__init__(parent)
        self.app = app
        self.theme: Palette = app.theme
        self.fonts: Fonts = app.fonts
        self.control = app.parent
        self.title_text = title
        self.hint_text = hint
        self.result = False
        self.new_recovery = ""
        self._cooldown_job = None

        self.title(title)
        self.configure(bg=self.theme.bg)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        _center(self, 470, 318)
        self.grab_set()
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._submit())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.panel = tk.Frame(self, bg=self.theme.bg)
        self.panel.pack(fill="both", expand=True, padx=32, pady=26)
        self._build_password_panel()
        self.dark_title_later()
        self.focus_later(self.password_entry, 60)

    # ---------- 密码面板 ----------

    def _clear(self) -> None:
        if self._cooldown_job:
            self.after_cancel(self._cooldown_job)
            self._cooldown_job = None
        for child in list(self.panel.children.values()):
            child.destroy()

    def _build_password_panel(self) -> None:
        theme, fonts = self.theme, self.fonts
        self._clear()
        label(self.panel, theme, self.title_text, font=fonts.h2).pack(anchor="w")
        label(
            self.panel,
            theme,
            self.hint_text or "输入家长密码后可以解锁电脑或修改设置",
            font=fonts.small,
            fg=theme.text3,
            wraplength=400,
        ).pack(anchor="w", pady=(6, 16))

        self.password_entry = _Entry(self.panel, theme, fonts, show="●")
        self.password_entry.pack(fill="x")
        self.error_label = label(self.panel, theme, "", font=fonts.small, fg=theme.bad, wraplength=400)
        self.error_label.pack(anchor="w", pady=(8, 0))

        actions = tk.Frame(self.panel, bg=theme.bg)
        actions.pack(side="bottom", fill="x")
        Button(actions, theme, fonts, "确定", self._submit, kind="primary", height=42).pack(side="right")
        Button(actions, theme, fonts, "取消", self._cancel, kind="quiet", height=42).pack(side="right", padx=(0, 10))
        Button(actions, theme, fonts, "忘记密码", self._build_recovery_panel, kind="quiet", height=42).pack(side="left")
        tk.Frame(self.panel, bg=theme.bg).pack(fill="both", expand=True)
        self._refresh_cooldown()

    def _refresh_cooldown(self) -> None:
        left = self.control.lockout_seconds()
        if left <= 0:
            self._cooldown_job = None
            return
        self.error_label.configure(text=f"尝试次数过多，请等 {left} 秒再试", fg=self.theme.bad)
        self._cooldown_job = self.after(1000, self._refresh_cooldown)

    # ---------- 恢复码面板 ----------

    def _build_recovery_panel(self) -> None:
        theme, fonts = self.theme, self.fonts
        self._clear()
        _center(self, 470, 476)
        label(self.panel, theme, "用恢复码重设密码", font=fonts.h2).pack(anchor="w")
        label(
            self.panel,
            theme,
            "恢复码是首次设置密码时抄下的 8 位字符，重设后会换一张新的。",
            font=fonts.small,
            fg=theme.text3,
            wraplength=406,
        ).pack(anchor="w", pady=(6, 16))

        label(self.panel, theme, "恢复码", font=fonts.small, fg=theme.text3).pack(anchor="w")
        self.code_entry = _Entry(self.panel, theme, fonts)
        self.code_entry.pack(fill="x", pady=(5, 12))
        label(self.panel, theme, "新密码（至少 6 位）", font=fonts.small, fg=theme.text3).pack(anchor="w")
        self.new_pass_entry = _Entry(self.panel, theme, fonts, show="●")
        self.new_pass_entry.pack(fill="x", pady=(5, 12))
        label(self.panel, theme, "再输一次", font=fonts.small, fg=theme.text3).pack(anchor="w")
        self.new_pass2_entry = _Entry(self.panel, theme, fonts, show="●")
        self.new_pass2_entry.pack(fill="x", pady=(5, 0))
        self.error_label = label(self.panel, theme, "", font=fonts.small, fg=theme.bad, wraplength=406)
        self.error_label.pack(anchor="w", pady=(10, 0))

        # 先把按钮钉在底部，再放弹性留白，否则留白会把按钮挤出可视区
        actions = tk.Frame(self.panel, bg=theme.bg)
        actions.pack(side="bottom", fill="x")
        Button(actions, theme, fonts, "重设密码", self._do_reset, kind="primary", height=42).pack(side="right")
        Button(actions, theme, fonts, "返回", self._build_password_panel, kind="quiet", height=42).pack(
            side="right", padx=(0, 10)
        )
        tk.Frame(self.panel, bg=theme.bg).pack(fill="both", expand=True)
        self.focus_later(self.code_entry, 30)

    def _do_reset(self) -> None:
        code = self.code_entry.get().strip()
        first = self.new_pass_entry.get()
        second = self.new_pass2_entry.get()
        if not code:
            self.error_label.configure(text="请填写恢复码", fg=self.theme.bad)
            return
        if first != second:
            self.error_label.configure(text="两次输入的密码不一致", fg=self.theme.bad)
            return
        ok, message, fresh = self.control.reset_with_recovery(code, first)
        if not ok:
            self.error_label.configure(text=message, fg=self.theme.bad)
            if self.control.lockout_seconds() > 0:
                self._refresh_cooldown()
            return
        self.new_recovery = fresh
        self._show_recovery(fresh, "密码已重设")

    def _show_recovery(self, code: str, headline: str) -> None:
        theme, fonts = self.theme, self.fonts
        self._clear()
        label(self.panel, theme, headline, font=fonts.h2).pack(anchor="w")
        label(
            self.panel,
            theme,
            "这是新的恢复码，请立刻抄下来。它只会显示这一次。",
            font=fonts.small,
            fg=theme.text3,
            wraplength=400,
        ).pack(anchor="w", pady=(6, 16))
        box = tk.Frame(self.panel, bg=theme.surface2, highlightbackground=theme.accent, highlightthickness=1)
        box.pack(fill="x")
        label(box, theme, code, font=(fonts.family, 24, "bold"), fg=theme.accent).pack(pady=16)
        actions = tk.Frame(self.panel, bg=theme.bg)
        actions.pack(side="bottom", fill="x")
        Button(actions, theme, fonts, "我已抄下", self._finish_ok, kind="primary", height=42).pack(side="right")

    # ---------- 提交 ----------

    def _submit(self) -> None:
        if self.control.lockout_seconds() > 0:
            self._refresh_cooldown()
            return
        value = self.password_entry.get()
        if not value:
            self.error_label.configure(text="请输入密码", fg=self.theme.bad)
            return
        passed, state = self.control.check(value)
        if passed:
            self.result = True
            self.destroy()
            return
        if state == "cooldown":
            self._refresh_cooldown()
            return
        if state == "nopass":
            self.error_label.configure(text="还没有设置家长密码", fg=self.theme.bad)
            return
        left = self.control.fails_left()
        self.error_label.configure(text=f"密码不对，还能试 {left} 次", fg=self.theme.bad)
        self.password_entry.clear()
        self.password_entry.focus()

    def _finish_ok(self) -> None:
        self.result = True
        self.destroy()

    def _cancel(self) -> None:
        self.result = False
        self.destroy()

    @classmethod
    def ask(cls, parent, app, title: str = "家长密码", hint: str = "") -> tuple[bool, str]:
        """弹出并等待，返回 (是否通过, 新恢复码)。"""
        dialog = cls(parent, app, title, hint)
        parent.wait_window(dialog)
        return dialog.result, dialog.new_recovery


class ParentSetupDialog(_DialogBase):
    """首次设置密码：两步，第二步强制展示恢复码。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.theme: Palette = app.theme
        self.fonts: Fonts = app.fonts
        self.control = app.parent
        self.result = False
        self.recovery = ""
        self._was_enrolled = bool(self.control.has_password)

        self.title("设置家长密码")
        self.configure(bg=self.theme.bg)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        _center(self, 520, 504)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.bind("<Escape>", lambda _e: self._skip())
        self.panel = tk.Frame(self, bg=self.theme.bg)
        self.panel.pack(fill="both", expand=True, padx=36, pady=30)
        self._build_form()
        self.dark_title_later()

    def _clear(self) -> None:
        for child in list(self.panel.children.values()):
            child.destroy()

    def _build_form(self) -> None:
        theme, fonts = self.theme, self.fonts
        self._clear()
        label(self.panel, theme, "设置家长密码", font=fonts.h1).pack(anchor="w")
        label(
            self.panel,
            theme,
            "设好之后，打开程序会先锁屏答题，\n"
            "答够时长才能解锁电脑。\n"
            "进入设置、临时解锁、退出程序都要用这个密码。",
            font=fonts.body,
            fg=theme.text2,
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(8, 20))

        label(self.panel, theme, f"密码（至少 6 位）", font=fonts.small, fg=theme.text3).pack(anchor="w")
        self.pass1 = _Entry(self.panel, theme, fonts, show="●")
        self.pass1.pack(fill="x", pady=(6, 12))
        label(self.panel, theme, "再输一次", font=fonts.small, fg=theme.text3).pack(anchor="w")
        self.pass2 = _Entry(self.panel, theme, fonts, show="●")
        self.pass2.pack(fill="x", pady=(6, 0))

        self.error_label = label(self.panel, theme, "", font=fonts.small, fg=theme.bad, wraplength=430)
        self.error_label.pack(anchor="w", pady=(10, 0))

        actions = tk.Frame(self.panel, bg=theme.bg)
        actions.pack(side="bottom", fill="x")
        Button(actions, theme, fonts, "保存并生成恢复码", self._save, kind="primary", height=44).pack(side="right")
        Button(actions, theme, fonts, "稍后再说", self._skip, kind="quiet", height=44).pack(side="right", padx=(0, 10))
        self.focus_later(self.pass1, 40)
        self.bind("<Return>", lambda _e: self._save())

    def _save(self) -> None:
        first = self.pass1.get()
        second = self.pass2.get()
        if first != second:
            self.error_label.configure(text="两次输入的密码不一致", fg=self.theme.bad)
            return
        ok, message, code = self.control.set_password(first)
        if not ok:
            self.error_label.configure(text=message, fg=self.theme.bad)
            return
        self.recovery = code
        self._show_recovery()

    def _show_recovery(self) -> None:
        theme, fonts = self.theme, self.fonts
        self._clear()
        self.unbind("<Return>")
        label(self.panel, theme, "把恢复码抄下来", font=fonts.h1).pack(anchor="w")
        label(
            self.panel,
            theme,
            "忘记密码时用它重设。只显示这一次，关了就没有了。",
            font=fonts.body,
            fg=theme.text2,
            wraplength=448,
        ).pack(anchor="w", pady=(8, 18))
        box = tk.Frame(self.panel, bg=theme.surface2, highlightbackground=theme.accent, highlightthickness=1)
        box.pack(fill="x")
        label(box, theme, self.recovery, font=(fonts.family, 30, "bold"), fg=theme.accent).pack(pady=(20, 8))
        label(box, theme, "例如抄在课本扉页或贴在显示器背面", font=fonts.small, fg=theme.text3).pack(pady=(0, 18))

        actions = tk.Frame(self.panel, bg=theme.bg)
        actions.pack(side="bottom", fill="x")
        Button(actions, theme, fonts, "我已抄下，开始使用", self._done, kind="primary", height=44).pack(side="right")

    def _done(self) -> None:
        self.result = True
        self.destroy()

    def _skip(self) -> None:
        # 中途退出等于没设密码：撤掉半截写入，并且不再每次启动都来问
        if self.control.has_password and not self._was_enrolled:
            self.control.cfg["password"] = {}
            self.control.cfg["recovery"] = {"hash": "", "salt": "", "iters": 0, "used": False}
            self.control.cfg["setupDone"] = False
            self.control.st.save_state()
        if not self._was_enrolled:
            self.control.set_enabled(False)
        self.result = False
        self.destroy()

    @classmethod
    def ask(cls, parent, app) -> tuple[bool, str]:
        dialog = cls(parent, app)
        parent.wait_window(dialog)
        return dialog.result, dialog.recovery


class LockBar(tk.Frame):
    """锁屏底部：余额进度 + 四档兑换按钮 + 家长解锁。"""

    def __init__(self, master, app):
        self.app = app
        self.theme: Palette = app.theme
        self.fonts: Fonts = app.fonts
        super().__init__(master, bg=self.theme.bg, height=146)
        self.pack_propagate(False)
        theme, fonts = self.theme, self.fonts

        tk.Frame(self, bg=theme.line, height=1).pack(side="top", fill="x")

        wrap = tk.Frame(self, bg=theme.bg)
        wrap.pack(fill="both", expand=True, padx=44, pady=(20, 20))

        left = tk.Frame(wrap, bg=theme.bg)
        left.pack(side="left", fill="both", expand=True)
        # 再把文字块整体垂直居中，与右侧按钮对齐
        stack = tk.Frame(left, bg=theme.bg)
        stack.pack(expand=True, fill="x", anchor="w")
        self.headline = label(stack, theme, "", font=fonts.h3)
        self.headline.pack(anchor="w")
        self.subline = label(stack, theme, "", font=fonts.small, fg=theme.text3)
        self.subline.pack(anchor="w", pady=(5, 0))
        self.bar = tk.Canvas(stack, height=8, bg=theme.bg, highlightthickness=0, bd=0)
        self.bar.pack(fill="x", pady=(12, 0))
        self.bar.bind("<Configure>", lambda _e: self._draw_bar())

        right = tk.Frame(wrap, bg=theme.bg)
        right.pack(side="right", padx=(28, 0))
        self.buttons: dict[int, Button] = {}
        for minutes in self.app.parent.tiers:
            btn = Button(
                right,
                theme,
                fonts,
                f"{minutes} 分钟",
                command=lambda m=minutes: self.app.request_unlock(m),
                kind="ghost",
                height=44,
                enabled=False,
            )
            btn.pack(side="left", padx=(0, 10))
            self.buttons[minutes] = btn
        Button(
            right,
            theme,
            fonts,
            "家长解锁",
            command=self.app.open_parent_gate,
            kind="quiet",
            height=44,
        ).pack(side="left", padx=(6, 0))

        self._ratio = 0.0
        self.refresh()

    def _draw_bar(self) -> None:
        theme = self.theme
        self.bar.delete("all")
        width = max(60, self.bar.winfo_width())
        height = 8
        track = mix(theme.text3, theme.bg, 0.55)
        round_rect(self.bar, 0, 0, width, height, height / 2, fill=track, outline=track)
        filled = int(width * max(0.0, min(1.0, self._ratio)))
        if filled > 2:
            color = self.theme.ok if self._ratio >= 1 else self.theme.accent
            round_rect(self.bar, 0, 0, filled, height, height / 2, fill=color, outline=color)

    def refresh(self) -> None:
        app, theme = self.app, self.theme
        engine = app.engine
        if engine is None:
            self.headline.configure(text="题库缺失，暂时无法答题")
            self.subline.configure(text="请让家长在题库页导入题库")
            self._ratio = 0.0
            self._draw_bar()
            return
        try:
            status = engine.status()
            options = engine.redeem_options(list(self.buttons.keys()))
        except Exception:  # pragma: no cover - 状态异常不应打断锁屏
            self.headline.configure(text="状态读取失败")
            self.subline.configure(text="")
            return

        credit = float(status.get("remainingMinutes") or 0)
        tiers = list(self.buttons.keys())
        smallest = tiers[0] if tiers else 10
        largest = tiers[-1] if tiers else 25
        daily_left = max(0.0, float(status.get("dailyMinutes") or 0) - float(status.get("usedMinutes") or 0))

        if status.get("reason") == "quota":
            self.headline.configure(text="今天的额度已经用完")
            self.subline.configure(text="明天再答，或者请家长临时解锁")
            self._ratio = 1.0
        elif credit >= smallest:
            usable = [o["minutes"] for o in options if o["enabled"]]
            if usable:
                self.headline.configure(text=f"余额 {credit:g} 分钟，选一档解锁电脑")
                self.subline.configure(text=f"解锁后倒计时归零会自动回到这里 · 今天还剩 {daily_left:g} 分钟额度")
            else:
                self.headline.configure(text=f"余额 {credit:g} 分钟")
                self.subline.configure(text=f"今天的总时长只剩 {daily_left:g} 分钟，不够开任何一档")
            self._ratio = min(1.0, credit / max(1, largest))
        else:
            gap = smallest - credit
            self.headline.configure(text=f"还差 {gap:g} 分钟就能解锁 {smallest} 分钟")
            self.subline.configure(text="答完这一组就有了")
            self._ratio = credit / max(1, smallest)

        for option in options:
            button = self.buttons.get(option["minutes"])
            if not button:
                continue
            if option["enabled"]:
                button.set_text(f"{option['minutes']} 分钟")
                button.set_enabled(True)
                button.kind = "primary"
            else:
                button.set_text(f"{option['minutes']} 分钟 · 差 {option['short']}")
                button.set_enabled(False)
                button.kind = "ghost"
            button._draw()
        self._draw_bar()


class ParentMenu(_DialogBase):
    """家长验证通过后的操作面板。"""

    def __init__(self, parent, app, new_recovery: str = ""):
        super().__init__(parent)
        self.app = app
        self.theme: Palette = app.theme
        self.fonts: Fonts = app.fonts
        self.new_recovery = new_recovery

        self.title("家长操作")
        self.configure(bg=self.theme.bg)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        _center(self, 480, 430 if new_recovery else 390)
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build()
        self.dark_title_later()

    def _build(self) -> None:
        theme, fonts = self.theme, self.fonts
        panel = tk.Frame(self, bg=theme.bg)
        panel.pack(fill="both", expand=True, padx=30, pady=24)

        label(panel, theme, "家长操作", font=fonts.h2).pack(anchor="w")

        status: dict = {}
        if self.app.engine:
            try:
                status = self.app.engine.status()
            except Exception:  # pragma: no cover
                status = {}
        used = float(status.get("usedMinutes") or 0)
        left = float(status.get("remainingMinutes") or 0)
        label(
            panel,
            theme,
            f"今天已用 {used:g} 分钟 · 剩余额度 {left:g} 分钟",
            font=fonts.small,
            fg=theme.text3,
        ).pack(anchor="w", pady=(6, 16))

        if self.new_recovery:
            box = tk.Frame(panel, bg=theme.surface2, highlightbackground=theme.accent, highlightthickness=1)
            box.pack(fill="x", pady=(0, 16))
            label(box, theme, "新的恢复码（请抄下来）", font=fonts.tiny, fg=theme.text3).pack(
                anchor="w", padx=16, pady=(10, 0)
            )
            label(box, theme, self.new_recovery, font=(fonts.family, 19, "bold"), fg=theme.accent).pack(
                anchor="w", padx=16, pady=(2, 12)
            )

        actions = tk.Frame(panel, bg=theme.bg)
        actions.pack(fill="x")
        Button(actions, theme, fonts, "解锁 30 分钟", lambda: self._unlock(30), kind="primary", height=44).pack(
            fill="x"
        )
        Button(actions, theme, fonts, "解锁到明天零点", self._unlock_tomorrow, kind="ghost", height=44).pack(
            fill="x", pady=(8, 0)
        )
        if self.app.lock_mode:
            Button(actions, theme, fonts, "立即回锁", self._lock_now, kind="ghost", height=44).pack(
                fill="x", pady=(8, 0)
            )
        Button(actions, theme, fonts, "退出程序", self._quit, kind="danger", height=44).pack(fill="x", pady=(8, 0))
        Button(actions, theme, fonts, "关闭", self.destroy, kind="quiet", height=38).pack(fill="x", pady=(10, 0))

    def _unlock(self, minutes: int) -> None:
        self.destroy()
        self.app.parent_unlock(minutes)

    def _unlock_tomorrow(self) -> None:
        self.destroy()
        self.app.parent_unlock(until_tomorrow=True)

    def _lock_now(self) -> None:
        self.destroy()
        self.app.end_unlock_early()

    def _quit(self) -> None:
        self.destroy()
        self.app.on_close(force=True)
