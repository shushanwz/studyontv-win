"""答题页：开始 → 作答 → 反馈 → 结算 / 使用计时。

电视端的遥控器交互（方向键移焦点、OK 确认）在这里映射为：
  * 鼠标点击选项直接作答
  * 字母 A–H / 数字 1–8 快捷键选择
  * ↑↓←→ 移动高亮，Enter 确认，Esc 返回
"""

from __future__ import annotations

import random
import tkinter as tk
from tkinter import messagebox

from ..core.engine import EngineError
from ..core.models import LETTERS, Question
from .theme import mix, wrap_text
from .widgets import Button, OptionCard, Pill, RoundPanel, round_rect

PRAISE = ["太棒了！", "答对啦！", "完全正确！", "真厉害！", "好样的，继续保持！", "漂亮！你越来越熟练了"]
ENCOURAGE = ["没关系，记住正确答案就好", "差一点点，下一题加油！", "错误也是学习的一部分", "别灰心，再接再厉！"]

MODE_LABEL = {"round": "本组任务", "streak": "连续答对", "practice": "自由练习"}


def plain_math(text: str) -> str:
    """把常见的 LaTeX 写法转成可读的纯文本（桌面版不渲染公式）。"""
    if not text:
        return ""
    result = str(text)
    replacements = [
        ("\\times", "×"),
        ("\\div", "÷"),
        ("\\cdot", "·"),
        ("\\pm", "±"),
        ("\\circ", "°"),
        ("\\pi", "π"),
        ("\\alpha", "α"),
        ("\\beta", "β"),
        ("\\theta", "θ"),
        ("\\le", "≤"),
        ("\\leq", "≤"),
        ("\\ge", "≥"),
        ("\\geq", "≥"),
        ("\\neq", "≠"),
        ("\\approx", "≈"),
        ("\\infty", "∞"),
        ("\\sqrt", "√"),
        ("\\left", ""),
        ("\\right", ""),
        ("\\quad", " "),
        ("\\,", " "),
        ("\\;", " "),
    ]
    for needle, value in replacements:
        result = result.replace(needle, value)
    # \frac{a}{b} -> (a)/(b)
    while "\\frac{" in result:
        start = result.find("\\frac{")
        depth = 0
        pos = start + 5
        numerator = ""
        while pos < len(result):
            char = result[pos]
            if char == "{":
                depth += 1
                if depth == 1:
                    pos += 1
                    continue
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
            numerator += char
            pos += 1
        if pos >= len(result) or pos + 1 >= len(result) or result[pos + 1] != "{":
            result = result[:start] + numerator + result[pos + 1:]
            continue
        denominator = ""
        pos += 1
        depth = 0
        pos += 1
        while pos < len(result):
            char = result[pos]
            if char == "{":
                depth += 1
                if depth == 1:
                    pos += 1
                    continue
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
            denominator += char
            pos += 1
        result = result[:start] + f"({numerator})/({denominator})" + result[pos + 1:]
    result = result.replace("^{", "^").replace("_{", "_").replace("}", "").replace("{", "")
    result = result.replace("$", "")
    return result


class QuizPage(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        super().__init__(master, bg=app.theme.bg)
        self.app = app
        self.view = "start"
        self.round: dict | None = None
        self.cards: list[OptionCard] = []
        self.highlight = 0
        self.selected: list[int] = []
        self.answered = False
        self.feedback: dict | None = None
        self.busy = False
        self.input_box: tk.Text | None = None
        self.pending_self: dict | None = None
        self._auto_job = None
        self._watch_job = None
        self._watch_total = 0
        self._watch_left = 0
        self._watch_paused = False
        self.stage = tk.Frame(self, bg=app.theme.bg)
        self.stage.pack(fill="both", expand=True, padx=54, pady=24)
        self.render()

    # ------------------------------------------------------------ 生命周期

    def on_show(self) -> None:
        if self.view == "watch":
            return
        self.refresh_entry()

    def refresh_entry(self) -> None:
        """进入答题页：该拦的先拦，有没做完的一组就接着做，否则给封面。"""
        app = self.app
        if not app.engine:
            self.show_error(app.engine_error or "题库加载失败")
            return
        status = app.engine.status()
        rules = app.engine.rules()
        if rules.playMode != "practice" and status.get("reason") in ("quota", "rounds", "schedule"):
            self.show_blocked(status["reason"], status)
            return
        if status.get("hasRound"):
            if self.view in ("question", "self") and self.round:
                return  # 界面已经在答题中，别重建打断
            # 上一组没答完（比如中途关掉程序），直接接着来
            self.reload()
            return
        self.show_start()

    def on_status_changed(self) -> None:
        # 开始页的数据由 on_show 刷新，这里不重建控件，避免计时刷新导致闪烁
        return

    def on_hide(self) -> None:
        self._stop_watch_timer()

    def reload(self) -> None:
        app = self.app
        self._cancel_auto()
        if not app.engine:
            self.show_error(app.engine_error or "题库加载失败")
            return
        self.round = None
        self.answered = False
        self.selected = []
        self.highlight = 0
        self.feedback = None
        self.pending_self = None
        self.busy = False
        try:
            result = app.engine.start()
        except EngineError as exc:
            self.show_error(str(exc))
            return
        if result.get("blocked"):
            self.show_blocked(result["blocked"], result.get("status", {}))
            return
        if result.get("pending_self"):
            self.pending_self = dict(result)
            self.pending_self["_answerText"] = "（答案已提交，请对照参考答案判断是否算对）"
            self.round = {"question": result.get("question", {})}
            self.view = "self"
            self.render()
            return
        self.round = result
        self.view = "question"
        self.render()

    # ------------------------------------------------------------ 渲染入口

    def render(self) -> None:
        for child in self.stage.winfo_children():
            child.destroy()
        self.cards = []
        self.input_box = None
        self.options_frame = None
        self.actions_frame = None
        self.self_labels = []
        if self.view == "self" and self.pending_self:
            self._render_self()
        elif self.view == "question" and self.round:
            self._render_question()
        elif self.view == "result":
            self._render_result()
        elif self.view == "blocked":
            self._render_blocked()
        elif self.view == "watch":
            self._render_watch()
        elif self.view == "error":
            self._render_error()
        else:
            self._render_start()

    # ------------------------------------------------------------ 开始页

    def _render_start(self) -> None:
        theme, fonts, app = self.app.theme, self.app.fonts, self.app
        engine = app.engine
        if not engine:
            # 题库目录为空或全部损坏时，不要在主界面直接抛异常，给出可操作的提示
            self.show_error(app.engine_error or "题库加载失败")
            return
        rules = engine.rules()
        status = engine.status()

        self.view = "start"
        panel = RoundPanel(self.stage, theme, radius=22, padding=42)
        panel.place(relx=0.5, rely=0.46, anchor="center")
        inner = panel.body

        tk.Label(inner, text="准备好开始了吗？", bg=theme.surface, fg=theme.text, font=fonts.h1).pack(anchor="w")
        tk.Label(
            inner,
            text=f"{MODE_LABEL.get(rules.playMode, rules.playMode)} · 每组 {rules.questionsPerRound} 题 · "
            f"答对 {int(round(rules.passRatio * 100))}% 通过",
            bg=theme.surface,
            fg=theme.text2,
            font=fonts.body,
        ).pack(anchor="w", pady=(10, 0))

        reward_text = (
            f"每题按星级奖励，完成后结算（1★ {rules.difficultyRewards.get('1', 1):g} 分 … "
            f"5★ {rules.difficultyRewards.get('5', 5):g} 分）"
            if rules.difficultyRewardEnabled
            else f"通过一组解锁 {rules.sessionMinutes} 分钟可用时间"
        )
        tk.Label(inner, text=reward_text, bg=theme.surface, fg=theme.text2, font=fonts.body).pack(anchor="w", pady=(4, 0))

        info = engine.bank_info()
        tk.Label(
            inner,
            text=f"当前题库：{info['name']} · {info['count']} 题",
            bg=theme.surface,
            fg=theme.text3,
            font=fonts.small,
        ).pack(anchor="w", pady=(10, 0))

        stats = tk.Frame(inner, bg=theme.surface)
        stats.pack(anchor="w", fill="x", pady=(22, 0))
        facts = [
            ("今日已完成", f"{status['roundsDoneToday']} / {rules.roundsPerDay} 组"),
            ("可用时间", f"{status['remainingMinutes']:g} 分钟"),
            ("加练池", f"{status['extraPool']} 题" if status["extraPool"] else "空"),
        ]
        for index, (name, value) in enumerate(facts):
            cell = tk.Frame(stats, bg=theme.surface)
            cell.grid(row=0, column=index, sticky="w", padx=(0, 44))
            tk.Label(cell, text=name, bg=theme.surface, fg=theme.text3, font=fonts.small).pack(anchor="w")
            tk.Label(cell, text=value, bg=theme.surface, fg=theme.text, font=fonts.body_bold).pack(anchor="w", pady=(3, 0))

        actions = tk.Frame(inner, bg=theme.surface)
        actions.pack(anchor="w", fill="x", pady=(28, 0))
        Button(actions, theme, fonts, "开始答题", self.begin, kind="primary", height=46, parent_bg=theme.surface).pack(
            side="left"
        )
        if status["extraPool"] > 0:
            Pill(actions, theme, fonts, f"加练池待做 {status['extraPool']} 题", parent_bg=theme.surface, accent=True).pack(
                side="left", padx=(14, 0)
            )

        hint = "回答后按 Enter 继续 · 全部快捷键见「关于」"
        tk.Label(inner, text=hint, bg=theme.surface, fg=theme.text3, font=fonts.small).pack(anchor="w", pady=(18, 0))

    def begin(self) -> None:
        self.reload()
        self.app.set_page("quiz")

    # ------------------------------------------------------------ 题目页

    def _render_question(self) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        round_ = self.round or {}
        question = Question(round_.get("question") or {})
        mode = round_.get("mode", "round")
        prompt = plain_math(question.q)
        options = [plain_math(item) for item in question.a]
        self.answered = False
        self.selected = []
        self.highlight = 0
        self.feedback = None
        self.view = "question"

        head = tk.Frame(self.stage, bg=theme.bg)
        head.pack(fill="x")
        left = tk.Frame(head, bg=theme.bg)
        left.pack(side="left", anchor="w")
        tag = "加练任务" if round_.get("extra") else MODE_LABEL.get(mode, "本组任务")
        tk.Label(left, text=f"{tag} · {question.stars()}", bg=theme.bg, fg=theme.accent, font=fonts.body_bold).pack(
            anchor="w"
        )
        sub = f"科目：{question.subject}" if question.subject else ""
        if sub:
            tk.Label(left, text=sub, bg=theme.bg, fg=theme.text3, font=fonts.small).pack(anchor="w", pady=(3, 0))

        counter = tk.Frame(head, bg=theme.bg)
        counter.pack(side="right", anchor="e")
        if mode == "streak":
            index_text, total_text = str(round_.get("streak", 0)), f"/ {round_.get('target', 0)}"
            tk.Label(counter, text="连续答对", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="left", padx=(0, 8))
        elif mode == "practice":
            index_text, total_text = str(int(round_.get("answered", 0)) + 1), "题"
        else:
            index_text = str(min(int(round_.get("answered", 0)) + 1, int(round_.get("target", 1))))
            total_text = f"/ {round_.get('target', 1)}"
        tk.Label(counter, text=index_text, bg=theme.bg, fg=theme.text, font=fonts.counter).pack(side="left")
        tk.Label(counter, text=f"  {total_text}", bg=theme.bg, fg=theme.text3, font=fonts.body).pack(side="left")

        foot = tk.Frame(self.stage, bg=theme.bg)
        foot.pack(side="bottom", fill="x", pady=(14, 0))
        pool = int(round_.get("extraPool") or 0)
        pool_text = f"加练池还剩 {pool} 题" if pool else ""
        tk.Label(foot, text=pool_text, bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="left")
        hint = "A–D 选择 · Enter 确认 · Esc 返回" if question.type not in ("text", "subjective") else "Ctrl+Enter 提交 · Esc 返回"
        tk.Label(foot, text=hint, bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="right")

        # 主体在剩余空间里垂直居中，避免全屏时内容全挤在顶部
        center = tk.Frame(self.stage, bg=theme.bg)
        center.pack(fill="both", expand=True)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(0, weight=1, minsize=8)
        center.rowconfigure(2, weight=1, minsize=8)
        content = tk.Frame(center, bg=theme.bg)
        content.grid(row=1, column=0, sticky="ew")
        self.content = content

        question_font = fonts.question if len(prompt) <= 60 else fonts.question_long
        self.question_label = tk.Label(
            content,
            text=prompt,
            bg=theme.bg,
            fg=theme.text,
            font=question_font,
            justify="left",
            anchor="w",
            wraplength=max(400, self.stage.winfo_width() - 20),
        )
        self.question_label.pack(fill="x", anchor="w", pady=(0, 24))
        content.bind("<Configure>", self._resize_question)

        if question.type in ("text", "subjective"):
            self._render_input(question)
        else:
            self._render_options(options)

    def _resize_question(self, event) -> None:
        label = getattr(self, "question_label", None)
        if label is not None and label.winfo_exists():
            label.configure(wraplength=max(360, event.width - 20))

    def _card_height(self, options: list[str], compact: bool) -> int:
        if compact:
            return 56
        longest = max((len(item) for item in options), default=0)
        return 110 if longest > 14 else 88

    def _render_options(self, options: list[str]) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        compact = self.answered
        grid = tk.Frame(self.content, bg=theme.bg)
        grid.pack(fill="x", anchor="nw")
        self.options_frame = grid
        self._build_options(grid, options, compact)

        multi = (self.round or {}).get("question", {}).get("type") == "multiple"
        if multi and not self.answered:
            actions = tk.Frame(self.content, bg=theme.bg)
            actions.pack(fill="x", pady=(14, 0))
            self.actions_frame = actions
            self.submit_button = Button(
                actions, theme, fonts, "确认所选答案", self.submit, kind="primary", height=44, parent_bg=theme.bg
            )
            self.submit_button.pack(anchor="w")

        self.feedback_frame = tk.Frame(self.content, bg=theme.bg)
        self.feedback_frame.pack(fill="x", pady=(16, 0))

    def _build_options(self, grid: tk.Frame, options: list[str], compact: bool) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        height = self._card_height(options, compact)
        columns = 2 if len(options) > 1 else 1
        for column in range(columns):
            grid.columnconfigure(column, weight=1, uniform="opt")
        self.cards = []
        for index, text in enumerate(options):
            card = OptionCard(
                grid,
                theme,
                fonts,
                LETTERS[index],
                text,
                state=OptionCard.STATE_NORMAL,
                compact=compact,
                on_click=(lambda i=index: self.choose(i)),
                parent_bg=theme.bg,
            )
            card.configure(height=height)
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=6, pady=6)
            self.cards.append(card)
        self._paint_options()

    def _compact_options(self) -> None:
        """作答后把选项压成单行卡片，给反馈面板腾出空间。"""
        grid = self.options_frame
        if grid is None or not grid.winfo_exists():
            return
        question = Question((self.round or {}).get("question") or {})
        options = [plain_math(item) for item in question.a]
        for child in grid.winfo_children():
            child.destroy()
        if self.actions_frame is not None and self.actions_frame.winfo_exists():
            self.actions_frame.destroy()
            self.actions_frame = None
        self._build_options(grid, options, compact=True)

    def _render_input(self, question: Question) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        subjective = question.type == "subjective"
        wrapper = tk.Frame(self.content, bg=theme.surface, highlightbackground=theme.line, highlightthickness=1)
        wrapper.pack(fill="x", anchor="nw")
        text = tk.Text(
            wrapper,
            height=6 if subjective else 3,
            bg=theme.surface,
            fg=theme.text,
            insertbackground=theme.text,
            font=(fonts.family, 14),
            bd=0,
            highlightthickness=0,
            wrap="word",
            padx=16,
            pady=14,
        )
        text.pack(fill="x")
        text.focus_set()
        self.input_box = text
        placeholder = "写下你的思路和答案…" if subjective else "请输入答案"
        text.insert("1.0", "")
        self._placeholder = placeholder
        self._placeholder_active = True
        text.insert("1.0", placeholder)
        text.configure(fg=theme.text3)

        def on_focus_in(_event=None):
            if self._placeholder_active:
                text.delete("1.0", "end")
                text.configure(fg=theme.text)
                self._placeholder_active = False

        def on_focus_out(_event=None):
            if not text.get("1.0", "end").strip():
                text.delete("1.0", "end")
                text.insert("1.0", placeholder)
                text.configure(fg=theme.text3)
                self._placeholder_active = True

        text.bind("<FocusIn>", on_focus_in)
        text.bind("<FocusOut>", on_focus_out)
        text.bind("<Control-Return>", lambda _e: (self.submit(), "break")[1])

        actions = tk.Frame(self.content, bg=theme.bg)
        actions.pack(fill="x", pady=(14, 0))
        label = "提交并自评" if subjective else "提交答案"
        Button(actions, theme, fonts, label, self.submit, kind="primary", height=44, parent_bg=theme.bg).pack(side="left")
        if subjective:
            tk.Label(
                actions,
                text="主观题没有自动判分，提交后对照参考答案自评",
                bg=theme.bg,
                fg=theme.text3,
                font=fonts.small,
            ).pack(side="left", padx=(14, 0))

        self.feedback_frame = tk.Frame(self.content, bg=theme.bg)
        self.feedback_frame.pack(fill="x", pady=(16, 0))

    # ------------------------------------------------------------ 交互

    def choose(self, index: int) -> None:
        if self.answered or self.busy or not self.round:
            return
        self.highlight = index
        qtype = self.round.get("question", {}).get("type")
        if qtype == "multiple":
            if index in self.selected:
                self.selected.remove(index)
            else:
                self.selected.append(index)
            self._paint_options()
        else:
            self.selected = [index]
            self._paint_options()
            self.submit()

    def submit(self) -> None:
        if self.answered or self.busy or not self.round:
            return
        question = Question(self.round.get("question") or {})
        text = ""
        if question.type in ("text", "subjective"):
            if self.input_box is not None:
                text = self.input_box.get("1.0", "end").strip()
                placeholder = getattr(self, "_placeholder", "")
                if getattr(self, "_placeholder_active", False) or (placeholder and text == placeholder):
                    text = ""
            if not text:
                self.app.toast("请先填写答案")
                if self.input_box is not None:
                    self.input_box.focus_set()
                return
        elif not self.selected:
            self.app.toast("请先选择答案")
            return

        self.busy = True
        try:
            result = self.app.engine.answer(self.selected, text)
        except EngineError as exc:
            self.busy = False
            self.app.toast(str(exc))
            return
        self.busy = False

        if result.get("pending_self"):
            self.pending_self = result
            self.pending_self["_answerText"] = text
            self.view = "self"
            self.render()
            return

        self.answered = True
        self.feedback = result
        self._compact_options()
        self._paint_options()
        self._show_feedback(result)
        self.app.refresh_status()

        auto = int(self.app.engine.rules().autoNextSeconds or 0)
        if auto > 0:
            self._auto_job = self.after(auto * 1000, self.next_question)

    def _paint_options(self) -> None:
        if not self.cards:
            return
        correct_indices = set()
        if self.feedback:
            correct_indices = set(self.feedback.get("correctIndices") or [])
            if self.feedback.get("answerText") and self.feedback.get("correctText"):
                correct_indices = set()
        for index, card in enumerate(self.cards):
            if self.answered and self.feedback:
                if index in correct_indices:
                    card.set_state(OptionCard.STATE_RIGHT)
                elif index in self.selected:
                    card.set_state(OptionCard.STATE_WRONG)
                else:
                    card.set_state(OptionCard.STATE_DIM)
            elif index in self.selected:
                card.set_state(OptionCard.STATE_SELECTED)
            elif index == self.highlight:
                card.set_state(OptionCard.STATE_FOCUS)
            else:
                card.set_state(OptionCard.STATE_NORMAL)

    def _show_feedback(self, result: dict) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        if not hasattr(self, "feedback_frame") or not self.feedback_frame.winfo_exists():
            return
        for child in self.feedback_frame.winfo_children():
            child.destroy()

        right = bool(result.get("correct"))
        frame = tk.Frame(
            self.feedback_frame,
            bg=theme.ok_soft if right else theme.bad_soft,
            highlightbackground=mix(theme.ok if right else theme.bad, theme.bg, 0.45),
            highlightthickness=1,
        )
        frame.pack(fill="x")
        inner = tk.Frame(frame, bg=theme.ok_soft if right else theme.bad_soft)
        inner.pack(fill="x", padx=20, pady=14)

        top = tk.Frame(inner, bg=theme.ok_soft if right else theme.bad_soft)
        top.pack(fill="x")
        badge = tk.Canvas(
            top, width=28, height=28, bg=theme.ok_soft if right else theme.bad_soft, highlightthickness=0, bd=0
        )
        badge.pack(side="left")
        badge.create_oval(1, 1, 27, 27, fill=theme.ok if right else theme.bad, outline="")
        badge.create_text(14, 14, text="✓" if right else "!", fill="#0A0A0C" if theme.name == "dark" else "#FFFFFF",
                          font=(fonts.family, 12, "bold"))

        title = PRAISE if right else ENCOURAGE

        tk.Label(
            top,
            text=random.choice(title),
            bg=theme.ok_soft if right else theme.bad_soft,
            fg=theme.ok if right else theme.bad,
            font=fonts.h3,
        ).pack(side="left", padx=(10, 0))

        answer_lines = []
        if not right:
            correct_text = result.get("correctText") or result.get("answerText") or ""
            if correct_text:
                answer_lines.append(f"正确答案：{plain_math(correct_text)}")
        tip = plain_math(result.get("tip") or "")
        if tip:
            answer_lines.append(f"解析：{tip}")
        if answer_lines:
            tk.Label(
                inner,
                text="\n".join(answer_lines),
                bg=theme.ok_soft if right else theme.bad_soft,
                fg=theme.text if right else theme.text,
                font=fonts.body,
                justify="left",
                anchor="w",
                wraplength=max(420, self.stage.winfo_width() - 120),
            ).pack(anchor="w", pady=(10, 0))

        actions = tk.Frame(inner, bg=theme.ok_soft if right else theme.bad_soft)
        actions.pack(fill="x", pady=(12, 0))
        label = "查看结果" if result.get("finished") else "继续"
        Button(
            actions,
            theme,
            fonts,
            label,
            self.next_question,
            kind="primary" if right else "danger",
            height=40,
            parent_bg=theme.ok_soft if right else theme.bad_soft,
        ).pack(side="left")
        extra_after = int(result.get("extraPoolAfter") or 0)
        if extra_after > 0 and not right:
            tk.Label(
                actions,
                text=f"错误累计 {int(result.get('wrongProgress') or 0)} · 加练池 {extra_after} 题",
                bg=theme.bad_soft,
                fg=theme.text2,
                font=fonts.small,
            ).pack(side="left", padx=(14, 0))

    def next_question(self) -> None:
        self._cancel_auto()
        result = self.feedback
        if not result:
            return
        if result.get("finished"):
            self.view = "result"
            self.render()
            self.app.refresh_status()
            return
        self.round = result.get("next")
        self.feedback = None
        self.answered = False
        self.selected = []
        self.highlight = 0
        self.render()

    def _cancel_auto(self) -> None:
        if self._auto_job:
            try:
                self.after_cancel(self._auto_job)
            except tk.TclError:
                pass
            self._auto_job = None

    # ------------------------------------------------------------ 主观题自评

    def _render_self(self) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        data = self.pending_self or {}
        # 与题目页一致：头部提示贴顶，其余内容在剩余空间里垂直居中
        top = tk.Frame(self.stage, bg=theme.bg)
        top.pack(fill="x")
        tk.Label(top, text="对照参考答案给自己打分", bg=theme.bg, fg=theme.accent, font=fonts.body_bold).pack(
            side="left", anchor="w"
        )
        tk.Label(top, text="Esc 返回", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="right", anchor="e")

        holder = tk.Frame(self.stage, bg=theme.bg)
        holder.pack(fill="both", expand=True)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1, minsize=8)
        holder.rowconfigure(2, weight=1, minsize=8)
        outer = tk.Frame(holder, bg=theme.bg)
        outer.grid(row=1, column=0, sticky="ew")
        outer.bind("<Configure>", self._resize_self)
        self.self_frame = outer
        self.self_labels = []
        stem = tk.Label(
            outer,
            text=plain_math((self.round or {}).get("question", {}).get("q", "")) if self.round else "",
            bg=theme.bg,
            fg=theme.text,
            font=fonts.h2,
            wraplength=max(500, self.stage.winfo_width() - 40),
            justify="left",
            anchor="w",
        )
        stem.pack(fill="x", anchor="w", pady=(10, 16))
        self.self_labels.append(stem)

        panel = tk.Frame(outer, bg=theme.surface, highlightbackground=theme.line, highlightthickness=1)
        panel.pack(fill="x")
        inner = tk.Frame(panel, bg=theme.surface)
        inner.pack(fill="x", padx=22, pady=18)
        inner.columnconfigure(1, weight=1)

        mine = data.get("_answerText") or ""
        rows = [("你的答案", plain_math(mine) or "（空）"), ("参考答案", plain_math(data.get("modelAnswer") or "（未提供）"))]
        if data.get("rubric"):
            rows.append(("评分标准", plain_math(data["rubric"])))
        for index, (name, value) in enumerate(rows):
            tk.Label(inner, text=name, bg=theme.surface, fg=theme.text3, font=fonts.small).grid(
                row=index, column=0, sticky="nw", pady=(0 if index == 0 else 10, 0), padx=(0, 16)
            )
            value_label = tk.Label(
                inner,
                text=value,
                bg=theme.surface,
                fg=theme.text,
                font=fonts.body,
                justify="left",
                anchor="w",
                wraplength=max(420, self.stage.winfo_width() - 220),
            )
            value_label.grid(row=index, column=1, sticky="w", pady=(0 if index == 0 else 10, 0))
            self.self_labels.append(value_label)

        actions = tk.Frame(outer, bg=theme.bg)
        actions.pack(fill="x", pady=(20, 0))
        Button(actions, theme, fonts, "我答对了", lambda: self._self_judge(True), kind="primary", height=44).pack(side="left")
        Button(actions, theme, fonts, "没答对", lambda: self._self_judge(False), kind="danger", height=44).pack(
            side="left", padx=(12, 0)
        )

    def _resize_self(self, event) -> None:
        labels = getattr(self, "self_labels", [])
        if not labels or not event.width:
            return
        stem_width = max(360, event.width - 20)
        value_width = max(300, event.width - 150)
        for index, label in enumerate(labels):
            if label.winfo_exists():
                label.configure(wraplength=stem_width if index == 0 else value_width)

    def _self_judge(self, correct: bool) -> None:
        try:
            result = self.app.engine.judge_self(correct)
        except EngineError as exc:
            self.app.toast(str(exc))
            return
        self.pending_self = None
        self.answered = True
        self.feedback = result
        self.round = self.round or {}
        if result.get("next"):
            self.round = result["next"]
        # 自评页没有选项卡片，直接跳到结果或下一题
        if result.get("finished"):
            self.view = "result"
            self.render()
            self.app.refresh_status()
        else:
            self.round = result.get("next")
            self.answered = False
            self.selected = []
            self.highlight = 0
            self.render()
            self.app.refresh_status()

    # ------------------------------------------------------------ 结果页

    def _render_result(self) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        result = self.feedback or {}
        passed = bool(result.get("passed"))
        finished = bool(result.get("finished"))
        status = self.app.engine.status() if self.app.engine else {}

        outer = tk.Frame(self.stage, bg=theme.bg)
        outer.place(relx=0.5, rely=0.45, anchor="center")
        inner = tk.Frame(outer, bg=theme.bg)
        inner.pack()

        badge = tk.Canvas(inner, width=76, height=76, bg=theme.bg, highlightthickness=0, bd=0)
        badge.pack()
        color = theme.ok if passed else theme.bad
        badge.create_oval(2, 2, 74, 74, fill=mix(color, theme.bg, 0.78), outline=color, width=2)
        badge.create_text(38, 38, text="✓" if passed else "!", fill=color, font=(fonts.family, 30, "bold"))

        title = "任务完成" if passed else "本组未通过"
        if finished and not passed:
            title = "本组未通过"
        tk.Label(inner, text=title, bg=theme.bg, fg=theme.text, font=fonts.h1).pack(pady=(18, 8))

        answered = int(result.get("roundAnswered") or 0)
        correct = int(result.get("roundCorrect") or 0)
        target = int(result.get("roundTarget") or 0)
        if passed:
            reward = result.get("rewardMinutes") or 0
            detail = f"答对 {correct} / {answered} 题 · 已解锁 {reward:g} 分钟"
            if status.get("reason") in ("quota", "rounds"):
                detail = f"答对 {correct} / {answered} 题 · 今天的额度已满，奖励未再累加"
        else:
            needed = self.app.engine.rules().pass_count() if self.app.engine else 0
            detail = f"答对 {correct} / {answered} 题，需要答对 {needed} 题"
        tk.Label(inner, text=detail, bg=theme.bg, fg=theme.text2, font=fonts.body).pack()

        if status.get("extraPool"):
            tk.Label(
                inner,
                text=f"加练池还有 {status['extraPool']} 题，下一组会继续出现",
                bg=theme.bg,
                fg=theme.text3,
                font=fonts.small,
            ).pack(pady=(6, 0))

        actions = tk.Frame(inner, bg=theme.bg)
        actions.pack(pady=(26, 0))
        if passed and status.get("remainingMinutes", 0) > 0:
            Button(actions, theme, fonts, "开始使用", self.start_watch, kind="primary", height=46).pack(side="left")
        Button(
            actions,
            theme,
            fonts,
            "再来一组" if not passed else "继续答题",
            self.begin,
            kind="ghost" if passed else "primary",
            height=46,
        ).pack(side="left", padx=(12, 0))
        Button(actions, theme, fonts, "返回", self.show_start, kind="quiet", height=46).pack(side="left", padx=(12, 0))

    def show_start(self) -> None:
        self.view = "start"
        self.round = None
        self.feedback = None
        self.render()

    # ------------------------------------------------------------ 拦截页

    def _render_blocked(self) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        status = getattr(self, "_blocked_status", {}) or {}
        reason = getattr(self, "_blocked_reason", "timeup")

        outer = tk.Frame(self.stage, bg=theme.bg)
        outer.place(relx=0.5, rely=0.45, anchor="center")
        inner = tk.Frame(outer, bg=theme.bg)
        inner.pack()

        badge = tk.Canvas(inner, width=72, height=72, bg=theme.bg, highlightthickness=0, bd=0)
        badge.pack()
        badge.create_oval(2, 2, 70, 70, fill=theme.surface2, outline=theme.line, width=2)
        badge.create_text(36, 36, text="⌛", fill=theme.text2, font=(fonts.family, 24))

        titles = {
            "quota": "今天的使用时间已用完",
            "rounds": "今天的任务已全部完成",
            "schedule": "还没到可用时段",
        }
        tk.Label(inner, text=titles.get(reason, "现在暂不可用"), bg=theme.bg, fg=theme.text, font=fonts.h1).pack(
            pady=(18, 8)
        )

        next_at = int(status.get("nextAvailableAt") or 0)
        if next_at:
            from datetime import datetime

            moment = datetime.fromtimestamp(next_at / 1000)
            tk.Label(
                inner,
                text=f"下次可用：{moment.month} 月 {moment.day} 日 {moment.hour:02d}:{moment.minute:02d}",
                bg=theme.bg,
                fg=theme.text2,
                font=fonts.body,
            ).pack()

        actions = tk.Frame(inner, bg=theme.bg)
        actions.pack(pady=(24, 0))
        Button(actions, theme, fonts, "返回", self.show_start, kind="ghost", height=44).pack(side="left")
        Button(actions, theme, fonts, "规则设置", lambda: self.app.set_page("rules"), kind="quiet", height=44).pack(
            side="left", padx=(12, 0)
        )

    def show_blocked(self, reason: str, status: dict) -> None:
        self._blocked_reason = reason
        self._blocked_status = status
        self.view = "blocked"
        self.render()
        self.app.refresh_status()

    # ------------------------------------------------------------ 使用计时

    def start_watch(self) -> None:
        status = self.app.engine.status()
        total = int(status.get("remainingSeconds") or 0)
        if total <= 0:
            self.app.toast("当前没有可用时间，先答一组题吧")
            return
        self._watch_total = total
        self._watch_left = total
        self._watch_paused = False
        self.view = "watch"
        self.render()

    def _render_watch(self) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        outer = tk.Frame(self.stage, bg=theme.bg)
        outer.place(relx=0.5, rely=0.42, anchor="center")
        inner = tk.Frame(outer, bg=theme.bg)
        inner.pack()

        tk.Label(inner, text="使用中", bg=theme.bg, fg=theme.text3, font=fonts.body_bold).pack()
        self.watch_label = tk.Label(inner, text=self._fmt(self._watch_left), bg=theme.bg, fg=theme.text, font=(fonts.family, 64, "bold"))
        self.watch_label.pack(pady=(6, 12))

        self.watch_bar = tk.Canvas(inner, width=420, height=8, bg=theme.bg, highlightthickness=0, bd=0)
        self.watch_bar.pack()
        self._draw_watch_bar()

        tk.Label(
            inner,
            text="计时结束会回到答题页；中途可以暂停或提前结束",
            bg=theme.bg,
            fg=theme.text3,
            font=fonts.small,
        ).pack(pady=(16, 0))

        actions = tk.Frame(inner, bg=theme.bg)
        actions.pack(pady=(22, 0))
        self.pause_button = Button(actions, theme, fonts, "暂停", self.toggle_pause, kind="ghost", height=44)
        self.pause_button.pack(side="left")
        Button(actions, theme, fonts, "结束使用", self.stop_watch, kind="primary", height=44).pack(side="left", padx=(12, 0))

        self._start_watch_timer()

    def _draw_watch_bar(self) -> None:
        theme = self.app.theme
        self.watch_bar.delete("all")
        width = 420
        total = max(1, self._watch_total)
        ratio = max(0.0, min(1.0, self._watch_left / total))
        round_rect(self.watch_bar, 0, 1, width, 7, 4, fill=theme.surface3, outline=theme.surface3)
        if ratio > 0.001:
            round_rect(self.watch_bar, 0, 1, max(8, width * ratio), 7, 4, fill=theme.accent, outline=theme.accent)

    def _start_watch_timer(self) -> None:
        self._stop_watch_timer()
        self._watch_job = self.after(1000, self._tick_watch)

    def _stop_watch_timer(self) -> None:
        if self._watch_job:
            try:
                self.after_cancel(self._watch_job)
            except tk.TclError:
                pass
            self._watch_job = None

    def _tick_watch(self) -> None:
        if self.view != "watch" or not self.app.engine:
            return
        if self._watch_paused:
            self._watch_job = self.after(1000, self._tick_watch)
            return
        used = self.app.engine.consume(1000)
        self._watch_left = max(0, self._watch_left - 1)
        if used <= 0:
            self._watch_left = 0
        if hasattr(self, "watch_label") and self.watch_label.winfo_exists():
            self.watch_label.configure(text=self._fmt(self._watch_left))
            self._draw_watch_bar()
        if self._watch_left <= 0:
            self.app.toast("使用时间到了，答题可以继续解锁")
            self.stop_watch()
            return
        self.app.refresh_status()
        self._watch_job = self.after(1000, self._tick_watch)

    @staticmethod
    def _fmt(seconds: int) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def toggle_pause(self) -> None:
        self._watch_paused = not self._watch_paused
        self.pause_button.set_text("继续" if self._watch_paused else "暂停")

    def stop_watch(self) -> None:
        self._stop_watch_timer()
        self.show_start()

    # ------------------------------------------------------------ 错误页

    def show_error(self, message: str) -> None:
        self._error_message = message
        self.view = "error"
        self.render()

    def _render_error(self) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        outer = tk.Frame(self.stage, bg=theme.bg)
        outer.place(relx=0.5, rely=0.45, anchor="center")
        inner = tk.Frame(outer, bg=theme.bg)
        inner.pack()
        tk.Label(inner, text="暂时没法开始答题", bg=theme.bg, fg=theme.text, font=fonts.h1).pack()
        tk.Label(
            inner,
            text=getattr(self, "_error_message", ""),
            bg=theme.bg,
            fg=theme.text2,
            font=fonts.body,
            wraplength=520,
            justify="center",
        ).pack(pady=(12, 0))
        actions = tk.Frame(inner, bg=theme.bg)
        actions.pack(pady=(22, 0))
        Button(actions, theme, fonts, "去题库", lambda: self.app.set_page("bank"), kind="primary", height=44).pack(
            side="left"
        )
        Button(actions, theme, fonts, "重试", self.reload, kind="ghost", height=44).pack(side="left", padx=(12, 0))

    # ------------------------------------------------------------ 键盘

    def handle_key(self, event) -> bool:
        widget_class = event.widget.winfo_class() if hasattr(event.widget, "winfo_class") else ""
        in_text = widget_class in ("Text", "Entry", "TEntry")

        if in_text:
            if event.keysym == "Escape":
                self.show_start()
                return True
            if event.keysym in ("Return", "KP_Enter") and (event.state & 0x4):
                self.submit()
                return True
            return False

        if event.keysym == "Escape":
            if self.view == "watch":
                self.stop_watch()
            elif self.view in ("question", "self", "result", "blocked"):
                self.show_start()
            return True

        if self.view in ("result", "blocked", "error", "self"):
            if event.keysym in ("Return", "KP_Enter", "space"):
                if self.view == "result" and (self.feedback or {}).get("finished"):
                    if (self.feedback or {}).get("passed"):
                        self.start_watch()
                    else:
                        self.begin()
                elif self.view == "error":
                    self.reload()
                return True
            return False

        if self.view != "question":
            return False

        question = Question((self.round or {}).get("question") or {})
        options = question.a or []
        if self.answered:
            if event.keysym in ("Return", "KP_Enter", "space"):
                self.next_question()
                return True
            return False

        if question.type in ("text", "subjective"):
            return False

        key = (event.char or "").lower()
        letters = LETTERS[: len(options)].lower()
        if key and key in letters:
            self.choose(letters.index(key))
            return True
        if key and key.isdigit():
            index = int(key) - 1
            if 0 <= index < len(options):
                self.choose(index)
                return True

        if event.keysym in ("Left", "Right", "Up", "Down"):
            step = -1 if event.keysym in ("Left", "Up") else 1
            if len(options) > 1:
                self.highlight = (self.highlight + step) % len(options)
                self._paint_options()
            return True

        if event.keysym in ("Return", "KP_Enter", "space"):
            if question.type == "multiple":
                if self.selected:
                    self.submit()
                else:
                    self.app.toast("用数字键或鼠标勾选选项，然后确认")
            else:
                self.choose(self.highlight)
            return True

        return False
