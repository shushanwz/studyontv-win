"""规则页：玩法、奖励、加练、出题范围与外观。"""

from __future__ import annotations

import tkinter as tk

from ..core.rules import PLAY_MODE_HINT, PLAY_MODE_LABEL, PLAY_MODES, Rules, valid_time
from tkinter import ttk

from .widgets import Button, ScrollFrame, Switch


class RulesPage(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        super().__init__(master, bg=app.theme.bg)
        self.app = app
        self.mode = tk.StringVar(value="round")
        self.nums: dict[str, tk.StringVar] = {}
        self.flags: dict[str, tk.BooleanVar] = {}
        self.stars: dict[str, tk.StringVar] = {}
        self.window_start = tk.StringVar(value="18:30")
        self.window_end = tk.StringVar(value="20:00")
        self.subjects: set[str] = set()
        self.levels: set[str] = set()
        self._switches: dict[str, Switch] = {}
        self.tier_vars: list[tk.StringVar] = []
        self.hard_flags: dict[str, tk.BooleanVar] = {}
        self._load_rules()
        self._build()

    # ------------------------------------------------------------ 数据

    def on_show(self) -> None:
        self._load_rules()
        self._rebuild()

    def _load_rules(self) -> None:
        rules = self.app.engine.rules() if self.app.engine else Rules()
        self.mode.set(rules.playMode)
        self.nums = {
            "questionsPerRound": tk.StringVar(value=str(rules.questionsPerRound)),
            "passPercent": tk.StringVar(value=str(int(round(rules.passRatio * 100)))),
            "sessionMinutes": tk.StringVar(value=str(rules.sessionMinutes)),
            "dailyMinutes": tk.StringVar(value=str(rules.dailyMinutes)),
            "roundsPerDay": tk.StringVar(value=str(rules.roundsPerDay)),
            "wrongThreshold": tk.StringVar(value=str(rules.wrongThreshold)),
            "extraQuestions": tk.StringVar(value=str(rules.extraQuestions)),
            "autoNextSeconds": tk.StringVar(value=str(rules.autoNextSeconds)),
        }
        self.stars = {star: tk.StringVar(value=f"{rules.difficultyRewards.get(star, float(star)):g}") for star in
                      ("1", "2", "3", "4", "5")}
        self.flags = {
            "extraEnabled": tk.BooleanVar(value=rules.extraEnabled),
            "difficultyRewardEnabled": tk.BooleanVar(value=rules.difficultyRewardEnabled),
            "spacedRepetitionEnabled": tk.BooleanVar(value=rules.spacedRepetitionEnabled),
            "dailyWindowEnabled": tk.BooleanVar(value=rules.dailyWindowEnabled),
        }
        self.window_start.set(rules.windowStart)
        self.window_end.set(rules.windowEnd)
        self.subjects = set(rules.quizSubjects)
        self.levels = set(rules.quizLevels)

    # ------------------------------------------------------------ 构建

    def _rebuild(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._switches = {}
        self._build()

    def _build(self) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        scroll = ScrollFrame(self, theme, parent_bg=theme.bg)
        scroll.pack(fill="both", expand=True, padx=46, pady=22)
        self.scroll = scroll
        body = scroll.body

        head = tk.Frame(body, bg=theme.bg)
        head.pack(fill="x", pady=(0, 18))
        tk.Label(head, text="规则与奖励", bg=theme.bg, fg=theme.text, font=fonts.h1).pack(side="left")
        tk.Label(
            head,
            text="保存后对下一组任务生效，进行中的任务沿用开始时的规则",
            bg=theme.bg,
            fg=theme.text3,
            font=fonts.small,
        ).pack(side="left", padx=(14, 0), pady=(6, 0))
        Button(head, theme, fonts, "保存规则", self.save, kind="primary", height=40, padx=20).pack(side="right")

        # ---- 玩法 ----
        self._section(body, "玩法")
        mode_row = tk.Frame(body, bg=theme.bg)
        mode_row.pack(fill="x", pady=(0, 6))
        for index, mode in enumerate(PLAY_MODES):
            selected = self.mode.get() == mode
            card = tk.Frame(
                mode_row,
                bg=theme.accent_soft if selected else theme.surface,
                highlightbackground=theme.accent if selected else theme.line,
                highlightthickness=1,
                cursor="hand2",
            )
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 12))
            mode_row.columnconfigure(index, weight=1, uniform="mode")
            inner = tk.Frame(card, bg=theme.accent_soft if selected else theme.surface)
            inner.pack(fill="both", expand=True, padx=18, pady=16)
            name = tk.Label(
                inner,
                text=PLAY_MODE_LABEL[mode],
                bg=theme.accent_soft if selected else theme.surface,
                fg=theme.accent if selected else theme.text,
                font=fonts.h3,
                anchor="w",
            )
            name.pack(anchor="w")
            desc = tk.Label(
                inner,
                text=PLAY_MODE_HINT[mode],
                bg=theme.accent_soft if selected else theme.surface,
                fg=theme.text2,
                font=fonts.small,
                anchor="w",
                justify="left",
                wraplength=260,
            )
            desc.pack(anchor="w", pady=(6, 0))
            for widget in (card, inner, name, desc):
                widget.bind("<ButtonRelease-1>", lambda _e, m=mode: self._set_mode(m))

        # ---- 题量与通过条件 ----
        self._section(body, "题量与通过条件")
        grid = tk.Frame(body, bg=theme.bg)
        grid.pack(fill="x")
        self._number_cell(grid, 0, 0, "每组题量", self.nums["questionsPerRound"], 1, 100, "道")
        self._number_cell(grid, 0, 1, "通过正确率", self.nums["passPercent"], 5, 100, "%")
        self._number_cell(grid, 1, 0, "每组解锁时长", self.nums["sessionMinutes"], 1, 120, "分钟")
        self._number_cell(grid, 1, 1, "每天最多答几组", self.nums["roundsPerDay"], 1, 100, "组")

        self.pass_hint = tk.Label(body, text="", bg=theme.bg, fg=theme.text3, font=fonts.small)
        self.pass_hint.pack(anchor="w", pady=(4, 0))
        for var in (self.nums["questionsPerRound"], self.nums["passPercent"]):
            var.trace_add("write", lambda *_: self._update_pass_hint())
        self._update_pass_hint()

        # ---- 每日额度 ----
        self._section(body, "每日额度")
        grid2 = tk.Frame(body, bg=theme.bg)
        grid2.pack(fill="x")
        self._number_cell(grid2, 0, 0, "每天最多可用", self.nums["dailyMinutes"], 1, 480, "分钟")
        tk.Label(
            grid2,
            text="答题解锁的时长不能超过这个上限；用完当天不再发放",
            bg=theme.bg,
            fg=theme.text3,
            font=fonts.small,
        ).grid(row=0, column=1, sticky="w", padx=(20, 0), pady=(10, 0))

        # ---- 星级奖励 ----
        self._section(body, "星级奖励")
        self._switch_row(
            body,
            "difficultyRewardEnabled",
            "按题目难度发放奖励",
            "开启后，按每道答对题目的星级累计时长；关闭则按「每组解锁时长」发放",
        )
        star_row = tk.Frame(body, bg=theme.bg)
        star_row.pack(fill="x", padx=(0, 0), pady=(8, 0))
        for index, star in enumerate(("1", "2", "3", "4", "5")):
            cell = tk.Frame(star_row, bg=theme.bg)
            cell.grid(row=0, column=index, sticky="w", padx=(0, 26))
            tk.Label(cell, text="★" * int(star), bg=theme.bg, fg=theme.accent, font=fonts.body_bold).pack(anchor="w")
            box = tk.Frame(cell, bg=theme.bg)
            box.pack(anchor="w", pady=(4, 0))
            entry = self._spin(box, self.stars[star], 0.1, 120, 0.5, width=5)
            entry.pack(side="left")
            tk.Label(box, text="分钟", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="left", padx=(6, 0))

        # ---- 答错加练 ----
        self._section(body, "答错加练")
        self._switch_row(
            body,
            "extraEnabled",
            "累计答错后增加加练题",
            "每累计答错 N 题，加练池增加 M 道题；通过任务后要清完加练池才发放奖励",
        )
        grid3 = tk.Frame(body, bg=theme.bg)
        grid3.pack(fill="x", pady=(8, 0))
        self._number_cell(grid3, 0, 0, "每答错", self.nums["wrongThreshold"], 1, 100, "题")
        self._number_cell(grid3, 0, 1, "增加加练", self.nums["extraQuestions"], 1, 100, "题")

        # ---- 出题范围 ----
        self._section(body, "出题范围")
        tk.Label(
            body,
            text="不选表示使用题库里的全部题目；选中的科目 / 年级才会被抽到",
            bg=theme.bg,
            fg=theme.text3,
            font=fonts.small,
        ).pack(anchor="w", pady=(0, 6))
        bank = self.app.engine.bank if self.app.engine else None
        if bank:
            subject_values = bank.subjects()
            level_values = bank.levels()
            self._chips(body, "科目", subject_values, self.subjects)
            if level_values:
                self._chips(body, "年级", level_values, self.levels)
        else:
            tk.Label(body, text="（还没有题库）", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(anchor="w")

        # ---- 高级 ----
        self._section(body, "复习与自动化")
        self._switch_row(
            body,
            "spacedRepetitionEnabled",
            "间隔重复复习",
            "优先抽到期题：首次答对约 1 天后复习，答错约 10 分钟后优先复习",
        )
        auto_row = tk.Frame(body, bg=theme.bg)
        auto_row.pack(fill="x", pady=(8, 0))
        tk.Label(auto_row, text="答完自动进入下一题", bg=theme.bg, fg=theme.text2, font=fonts.body).pack(side="left")
        entry = self._spin(auto_row, self.nums["autoNextSeconds"], 0, 30, 1, width=5)
        entry.pack(side="left", padx=(10, 6))
        tk.Label(auto_row, text="秒（0 表示手动）", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="left")

        self._section(body, "可用时段")
        self._switch_row(
            body,
            "dailyWindowEnabled",
            "只在指定时段允许答题",
            "关闭时全天可用；开启后，时段外会停在提示页",
        )
        window_row = tk.Frame(body, bg=theme.bg)
        window_row.pack(fill="x", pady=(8, 0))
        tk.Label(window_row, text="从", bg=theme.bg, fg=theme.text2, font=fonts.body).pack(side="left")
        tk.Entry(
            window_row,
            textvariable=self.window_start,
            width=8,
            bg=theme.surface,
            fg=theme.text,
            insertbackground=theme.text,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.line,
            font=(fonts.family, 11),
        ).pack(side="left", padx=(8, 10), ipady=4)
        tk.Label(window_row, text="到", bg=theme.bg, fg=theme.text2, font=fonts.body).pack(side="left")
        tk.Entry(
            window_row,
            textvariable=self.window_end,
            width=8,
            bg=theme.surface,
            fg=theme.text,
            insertbackground=theme.text,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.line,
            font=(fonts.family, 11),
        ).pack(side="left", padx=(8, 10), ipady=4)
        tk.Label(window_row, text="格式 HH:MM", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="left")

        self._build_parent_section(body)

        self._section(body, "外观")
        theme_row = tk.Frame(body, bg=theme.bg)
        theme_row.pack(fill="x")
        Button(
            theme_row,
            theme,
            fonts,
            "深色主题",
            lambda: self.app.apply_theme("dark"),
            kind="primary" if theme.name == "dark" else "ghost",
            height=38,
        ).pack(side="left")
        Button(
            theme_row,
            theme,
            fonts,
            "浅色主题",
            lambda: self.app.apply_theme("light"),
            kind="primary" if theme.name == "light" else "ghost",
            height=38,
        ).pack(side="left", padx=(10, 0))

        foot = tk.Frame(body, bg=theme.bg)
        foot.pack(fill="x", pady=(26, 10))
        Button(foot, theme, fonts, "保存规则", self.save, kind="primary", height=44, padx=26).pack(side="left")
        Button(foot, theme, fonts, "恢复默认", self.reset_defaults, kind="quiet", height=44).pack(side="left", padx=(10, 0))
        tk.Label(
            foot,
            text="规则与题库都保存在程序目录的 data 文件夹，拷贝即可带走",
            bg=theme.bg,
            fg=theme.text3,
            font=fonts.small,
        ).pack(side="left", padx=(18, 0))

    # ------------------------------------------------------------ 家长控制

    def _build_parent_section(self, body) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        control = self.app.parent
        cfg = control.cfg
        hard = cfg.get("hardening") or {}

        self._section(body, "家长控制")

        has_password = control.has_password
        enabled = bool(cfg.get("enabled")) and has_password
        try:
            status = self.app.engine.status() if self.app.engine else {}
        except Exception:  # pragma: no cover - 状态异常不该挡住设置页
            status = {}
        left = float(status.get("remainingMinutes") or 0)

        if enabled:
            line = f"已开启 · 今日剩余额度 {left:g} 分钟 · 攒够额度才能解锁电脑"
            color = theme.ok
        elif has_password:
            line = "已暂停 · 打开程序不再锁屏，密码仍然有效"
            color = theme.text2
        else:
            line = "未设置密码 · 没设密码就不会锁屏，先设一个再启用"
            color = theme.bad
        tk.Label(body, text=line, bg=theme.bg, fg=color, font=fonts.body).pack(anchor="w")

        tier_row = tk.Frame(body, bg=theme.bg)
        tier_row.pack(fill="x", pady=(14, 0))
        tk.Label(tier_row, text="解锁档位", bg=theme.bg, fg=theme.text, font=fonts.body_bold).pack(side="left")
        existing = control.tiers
        self.tier_vars = []
        for index in range(4):
            value = existing[index] if index < len(existing) else 0
            var = tk.StringVar(value=str(value) if value else "")
            self.tier_vars.append(var)
            self._spin(tier_row, var, 1, 60, 5, width=4).pack(side="left", padx=(10 if index == 0 else 8, 0))
        tk.Label(tier_row, text="分钟（留空或 0 表示不要这一档）", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(
            side="left", padx=(10, 0)
        )

        self.hard_flags = {
            "keyboardHook": tk.BooleanVar(value=bool(hard.get("keyboardHook", True))),
            "clipCursor": tk.BooleanVar(value=bool(hard.get("clipCursor", True))),
            "watchdog": tk.BooleanVar(value=bool(hard.get("watchdog", True))),
            "disableTaskMgr": tk.BooleanVar(value=bool(hard.get("disableTaskMgr", False))),
        }
        self._parent_switch_row(
            body, "keyboardHook", "封锁切换键", "拦下 Win、Alt+Tab、Alt+F4、Ctrl+Esc，锁屏期间切不走"
        )
        self._parent_switch_row(body, "clipCursor", "限制鼠标范围", "光标锁在全屏窗口内，点不到任务栏")
        self._parent_switch_row(body, "watchdog", "看门狗", "进程被强行结束后，两三秒内自动把锁屏拉回来")
        self._parent_switch_row(
            body,
            "disableTaskMgr",
            "禁用任务管理器",
            "更硬，但会影响这台电脑的其他使用；程序正常退出时会自动恢复",
        )

        actions = tk.Frame(body, bg=theme.bg)
        actions.pack(fill="x", pady=(16, 0))
        Button(actions, theme, fonts, "修改家长密码", self._change_password, kind="ghost", height=38).pack(side="left")
        if self.app.lock_mode:
            Button(actions, theme, fonts, "立即回到锁屏", self._lock_now, kind="ghost", height=38).pack(
                side="left", padx=(10, 0)
            )
        Button(actions, theme, fonts, "停用家长控制", self._disable_parent, kind="quiet", height=38).pack(
            side="left", padx=(10, 0)
        )

    def _parent_switch_row(self, parent, key: str, title: str, hint: str) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        row = tk.Frame(parent, bg=theme.bg)
        row.pack(fill="x", pady=(10, 0))
        text = tk.Frame(row, bg=theme.bg)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, bg=theme.bg, fg=theme.text, font=fonts.body_bold).pack(anchor="w")
        tk.Label(
            text, text=hint, bg=theme.bg, fg=theme.text3, font=fonts.small, justify="left", anchor="w"
        ).pack(anchor="w", pady=(2, 0))
        var = self.hard_flags[key]
        Switch(row, theme, checked=var.get(), on_change=lambda value, v=var: v.set(value)).pack(
            side="right", padx=(16, 0)
        )

    def _change_password(self) -> None:
        from .page_lock import ParentSetupDialog, PasswordDialog

        passed, _code = PasswordDialog.ask(self.app, self.app, "修改家长密码", "先输入当前密码，验证后可以设新的")
        if not passed:
            return
        ok, _new_code = ParentSetupDialog.ask(self.app, self.app)
        if ok:
            self.app.toast("家长密码已更新，恢复码也已重新生成")
            self._rebuild()

    def _lock_now(self) -> None:
        self.app.back_to_lock()

    def _disable_parent(self) -> None:
        from .page_lock import PasswordDialog

        passed, _code = PasswordDialog.ask(self.app, self.app, "停用家长控制", "停用后打开程序不再锁屏")
        if not passed:
            return
        if not self.app.confirm("停用家长控制", "停用后这台电脑将不再需要答题解锁。确定停用？"):
            return
        self.app.parent.cfg["enabled"] = False
        self.app.parent.st.save_state()
        self.app.toast("家长控制已停用")
        if self.app.lock_mode:
            self.app.on_close(force=True)
        else:
            self._rebuild()

    def _save_parent(self) -> None:
        control = self.app.parent
        tiers: list[int] = []
        for var in self.tier_vars:
            raw = str(var.get()).strip()
            if not raw:
                continue
            try:
                value = int(float(raw))
            except ValueError:
                continue
            if value > 0:
                tiers.append(value)
        if tiers:
            ok, message = control.set_tiers(tiers)
            if not ok:
                self.app.toast(f"档位没保存：{message}")
                return
        hard = control.cfg.setdefault("hardening", {})
        for key, var in self.hard_flags.items():
            hard[key] = bool(var.get())
        control.st.save_state()
        self.app.reload_guard_config()

    # ------------------------------------------------------------ 组件

    def _section(self, parent, title: str) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        tk.Label(parent, text=title, bg=theme.bg, fg=theme.text, font=fonts.h3).pack(anchor="w", pady=(22, 8))
        tk.Frame(parent, bg=theme.line, height=1).pack(fill="x", pady=(0, 10))

    def _spin(self, parent, var, low, high, step, width=6) -> tk.Spinbox:
        theme, fonts = self.app.theme, self.app.fonts
        style = ttk.Style(self)
        style.configure(
            "Quiz.TSpinbox",
            fieldbackground=theme.surface,
            background=theme.surface2,
            foreground=theme.text,
            arrowcolor=theme.text2,
            bordercolor=theme.line,
            lightcolor=theme.line,
            darkcolor=theme.line,
            insertcolor=theme.text,
        )
        style.map(
            "Quiz.TSpinbox",
            fieldbackground=[("readonly", theme.surface)],
            foreground=[("readonly", theme.text)],
        )
        return ttk.Spinbox(
            parent,
            from_=low,
            to=high,
            increment=step,
            textvariable=var,
            width=width,
            style="Quiz.TSpinbox",
            font=(fonts.family, 11),
            justify="left",
        )

    def _number_cell(self, parent, row: int, column: int, label: str, var, low, high, unit: str) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        cell = tk.Frame(parent, bg=theme.bg)
        cell.grid(row=row, column=column, sticky="w", padx=(0, 40), pady=(0, 12))
        tk.Label(cell, text=label, bg=theme.bg, fg=theme.text2, font=fonts.body).pack(anchor="w")
        box = tk.Frame(cell, bg=theme.bg)
        box.pack(anchor="w", pady=(5, 0))
        spin = self._spin(box, var, low, high, 1, width=6)
        spin.pack(side="left")
        tk.Label(box, text=unit, bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="left", padx=(8, 0))

    def _switch_row(self, parent, key: str, title: str, hint: str) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        row = tk.Frame(parent, bg=theme.bg)
        row.pack(fill="x", pady=(4, 0))
        text = tk.Frame(row, bg=theme.bg)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, bg=theme.bg, fg=theme.text, font=fonts.body_bold).pack(anchor="w")
        tk.Label(text, text=hint, bg=theme.bg, fg=theme.text3, font=fonts.small, justify="left", anchor="w").pack(
            anchor="w", pady=(2, 0)
        )
        switch = Switch(row, theme, checked=self.flags[key].get(), on_change=lambda value: self.flags[key].set(value))
        switch.pack(side="right", padx=(16, 0))
        self._switches[key] = switch

    def _chips(self, parent, title: str, values: list[str], selected: set[str]) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        if not values:
            return
        row = tk.Frame(parent, bg=theme.bg)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text=title, bg=theme.bg, fg=theme.text3, font=fonts.small, width=4, anchor="w").pack(side="left")
        for value in values[:24]:
            active = value in selected
            chip = Button(
                row,
                theme,
                fonts,
                value,
                (lambda v=value, s=selected: self._toggle_chip(v, s)),
                kind="primary" if active else "ghost",
                height=32,
                padx=14,
                font=fonts.small,
            )
            chip.pack(side="left", padx=(0, 8))

    def _toggle_chip(self, value: str, bucket: set[str]) -> None:
        if value in bucket:
            bucket.discard(value)
        else:
            bucket.add(value)
        self._rebuild()

    def _set_mode(self, mode: str) -> None:
        self.mode.set(mode)
        self._rebuild()

    def _update_pass_hint(self) -> None:
        try:
            total = int(float(self.nums["questionsPerRound"].get()))
            percent = int(float(self.nums["passPercent"].get()))
        except (ValueError, KeyError):
            return
        need = max(1, int(-(-total * percent // 100)))
        if hasattr(self, "pass_hint") and self.pass_hint.winfo_exists():
            self.pass_hint.configure(text=f"每组 {total} 题时，至少答对 {need} 题才算通过")

    # ------------------------------------------------------------ 保存

    def save(self) -> None:
        engine = self.app.engine
        if not engine:
            return
        try:
            rules = Rules(
                playMode=self.mode.get(),
                questionsPerRound=self._int("questionsPerRound", 1, 100),
                passRatio=max(0.05, min(1.0, self._int("passPercent", 5, 100) / 100)),
                sessionMinutes=self._int("sessionMinutes", 1, 120),
                roundsPerDay=self._int("roundsPerDay", 1, 100),
                dailyMinutes=self._int("dailyMinutes", 1, 480),
                extraEnabled=self.flags["extraEnabled"].get(),
                wrongThreshold=self._int("wrongThreshold", 1, 100),
                extraQuestions=self._int("extraQuestions", 1, 100),
                difficultyRewardEnabled=self.flags["difficultyRewardEnabled"].get(),
                difficultyRewards={star: max(0.1, min(120.0, float(self.stars[star].get() or star)))
                                   for star in ("1", "2", "3", "4", "5")},
                spacedRepetitionEnabled=self.flags["spacedRepetitionEnabled"].get(),
                quizSubjects=sorted(self.subjects),
                quizLevels=sorted(self.levels),
                autoNextSeconds=self._int("autoNextSeconds", 0, 30),
                dailyWindowEnabled=self.flags["dailyWindowEnabled"].get(),
                windowStart=self.window_start.get().strip(),
                windowEnd=self.window_end.get().strip(),
            )
        except ValueError as exc:
            self.app.toast(str(exc))
            return

        if not valid_time(rules.windowStart) or not valid_time(rules.windowEnd):
            self.app.toast("时段格式需要是 HH:MM，例如 18:30")
            return
        if rules.dailyWindowEnabled and rules.windowStart == rules.windowEnd:
            self.app.toast("开始与结束时间不能相同")
            return

        engine.save_rules(rules)
        self._save_parent()
        self.app.toast("规则已保存，下一组任务生效")
        self.app.refresh_status()

    def _int(self, key: str, low: int, high: int) -> int:
        raw = self.nums[key].get().strip()
        try:
            value = int(float(raw))
        except ValueError:
            raise ValueError(f"「{raw}」不是有效数字") from None
        if not low <= value <= high:
            raise ValueError(f"数值需要在 {low}–{high} 之间")
        return value

    def reset_defaults(self) -> None:
        if not self.app.confirm("恢复默认", "把玩法、奖励与加练设置恢复为默认值？题库不受影响。"):
            return
        self.app.engine.save_rules(Rules())
        self.on_show()
        self.app.toast("已恢复默认规则")
        self.app.refresh_status()

    def handle_key(self, event) -> bool:
        return False
