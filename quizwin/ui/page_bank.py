"""题库页：题库切换、题目增删改、导入导出。"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..core.models import LETTERS, TYPE_LABEL, Bank, Question
from .theme import Fonts, Palette, apply_dark_title_bar, mix
from .widgets import Button, ScrollFrame, SlimScrollbar

TYPE_ORDER = ("single", "multiple", "boolean", "text", "subjective")


def style_tree(parent: tk.Misc, theme: Palette, fonts: Fonts) -> None:
    style = ttk.Style(parent)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Quiz.Treeview",
        background=theme.surface,
        fieldbackground=theme.surface,
        foreground=theme.text,
        rowheight=32,
        borderwidth=0,
        font=(fonts.family, 10),
    )
    style.configure(
        "Quiz.Treeview.Heading",
        background=theme.surface2,
        foreground=theme.text2,
        relief="flat",
        borderwidth=0,
        font=(fonts.family, 9, "bold"),
        padding=(8, 8),
    )
    style.map(
        "Quiz.Treeview",
        background=[("selected", theme.accent_soft)],
        foreground=[("selected", theme.text)],
    )
    style.map("Quiz.Treeview.Heading", background=[("active", theme.surface3)])
    style.configure(
        "TCombobox",
        fieldbackground=theme.surface2,
        background=theme.surface2,
        foreground=theme.text,
        arrowcolor=theme.text2,
        bordercolor=theme.line,
        lightcolor=theme.line,
        darkcolor=theme.line,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", theme.surface2)],
        foreground=[("readonly", theme.text)],
        selectbackground=[("readonly", theme.surface2)],
        selectforeground=[("readonly", theme.text)],
    )


def dark_scrollbar(parent: tk.Misc, theme: Palette, command) -> SlimScrollbar:
    return SlimScrollbar(parent, theme, command=command, parent_bg=theme.surface, width=10)


class BankRow(tk.Frame):
    def __init__(self, master, page: "BankPage", info, active: bool):
        theme, fonts = page.app.theme, page.app.fonts
        super().__init__(master, bg=theme.accent_soft if active else theme.surface2, cursor="hand2")
        self.page = page
        self.info = info
        self.active = active
        height = 68
        self.configure(height=height)
        self.pack_propagate(False)

        strip = tk.Frame(self, bg=theme.accent if active else theme.surface2, width=3)
        strip.pack(side="left", fill="y")

        body = tk.Frame(self, bg=theme.accent_soft if active else theme.surface2)
        body.pack(side="left", fill="both", expand=True, padx=12, pady=9)
        name = info.name if len(info.name) <= 18 else info.name[:17] + "…"
        tk.Label(
            body,
            text=name,
            bg=theme.accent_soft if active else theme.surface2,
            fg=theme.text if active else theme.text2,
            font=fonts.body_bold,
            anchor="w",
        ).pack(anchor="w")
        count_text = f"{info.count} 题" if info.count >= 0 else "文件无法解析"
        tk.Label(
            body,
            text=count_text,
            bg=theme.accent_soft if active else theme.surface2,
            fg=theme.accent if active else theme.text3,
            font=fonts.small,
            anchor="w",
        ).pack(anchor="w")

        for widget in (self, body, *body.winfo_children()):
            widget.bind("<ButtonRelease-1>", lambda _e: page.switch_bank(info))


class BankPage(tk.Frame):
    PLACEHOLDER = "搜索题干 / 选项"

    def __init__(self, master: tk.Misc, app):
        super().__init__(master, bg=app.theme.bg)
        self.app = app
        self.selected_id: str | None = None
        self.keyword = tk.StringVar(value="")
        self.type_filter = tk.StringVar(value="全部题型")
        self._build()

    # ------------------------------------------------------------ 构建

    def _build(self) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        for child in self.winfo_children():
            child.destroy()

        left = tk.Frame(self, bg=theme.bg, width=280)
        left.pack(side="left", fill="y", padx=(30, 16), pady=22)
        left.pack_propagate(False)
        left.grid_propagate(False)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)

        tk.Label(left, text="题库", bg=theme.bg, fg=theme.text, font=fonts.h2).grid(row=0, column=0, sticky="w")
        tk.Label(
            left,
            text="切换后立即生效，修改直接写入文件",
            bg=theme.bg,
            fg=theme.text3,
            font=fonts.small,
            wraplength=280,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 16))

        self.list_frame = ScrollFrame(left, theme, parent_bg=theme.bg)
        self.list_frame.grid(row=2, column=0, sticky="nsew")
        self.rows_holder = self.list_frame.body

        actions = tk.Frame(left, bg=theme.bg)
        actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        Button(actions, theme, fonts, "新建", self.create_bank, height=38, padx=16).pack(side="left")
        Button(actions, theme, fonts, "导入", self.import_bank, height=38, padx=16).pack(side="left", padx=(8, 0))
        Button(actions, theme, fonts, "导出", self.export_bank, height=38, padx=16).pack(side="left", padx=(8, 0))

        right = tk.Frame(self, bg=theme.bg)
        right.pack(side="left", fill="both", expand=True, padx=(0, 30), pady=22)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        head = tk.Frame(right, bg=theme.bg)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)

        title_row = tk.Frame(head, bg=theme.bg)
        title_row.grid(row=0, column=0, sticky="ew")
        self.title_label = tk.Label(title_row, text="题库", bg=theme.bg, fg=theme.text, font=fonts.h2, anchor="w")
        self.title_label.pack(side="left")

        head_actions = tk.Frame(title_row, bg=theme.bg)
        head_actions.pack(side="right")
        Button(head_actions, theme, fonts, "重命名", self.rename_bank, kind="quiet", height=36, padx=14).pack(
            side="left"
        )
        Button(head_actions, theme, fonts, "保存题库", self.save_bank, kind="ghost", height=36, padx=16).pack(
            side="left", padx=(8, 0)
        )

        info_row = tk.Frame(head, bg=theme.bg)
        info_row.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.meta_label = tk.Label(info_row, text="", bg=theme.bg, fg=theme.text3, font=fonts.small)
        self.meta_label.pack(side="left")
        self.dirty_label = tk.Label(info_row, text="", bg=theme.bg, fg=theme.accent, font=fonts.small)
        self.dirty_label.pack(side="left", padx=(10, 0))

        tools = tk.Frame(right, bg=theme.bg)
        tools.grid(row=1, column=0, sticky="ew", pady=(16, 10))

        search = tk.Entry(
            tools,
            bg=theme.surface,
            fg=theme.text3,
            insertbackground=theme.text,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.line,
            highlightcolor=theme.accent,
            font=(fonts.family, 10),
            width=26,
        )
        search.pack(side="left", ipady=6, ipadx=8)
        search.insert(0, self.PLACEHOLDER)
        self.keyword_entry = search

        def on_focus_in(_event=None):
            if search.get() == self.PLACEHOLDER:
                search.delete(0, "end")
                search.configure(fg=theme.text)

        def on_focus_out(_event=None):
            if not search.get().strip():
                search.delete(0, "end")
                search.insert(0, self.PLACEHOLDER)
                search.configure(fg=theme.text3)
                self.refresh_table()

        search.bind("<FocusIn>", on_focus_in)
        search.bind("<FocusOut>", on_focus_out)
        search.bind("<KeyRelease>", lambda _e: self.refresh_table())
        tk.Frame(tools, bg=theme.bg, width=12).pack(side="left")

        self.type_box = ttk.Combobox(
            tools,
            textvariable=self.type_filter,
            values=("全部题型",) + tuple(TYPE_LABEL[t] for t in TYPE_ORDER),
            state="readonly",
            width=10,
            font=(fonts.family, 10),
        )
        self.type_box.pack(side="left")
        self.type_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table())

        Button(tools, theme, fonts, "新增题目", self.new_question, kind="primary", height=36, padx=16).pack(
            side="right"
        )
        Button(tools, theme, fonts, "删除", self.delete_question, kind="danger", height=36, padx=14).pack(
            side="right", padx=(0, 8)
        )
        Button(tools, theme, fonts, "编辑", self.edit_question, height=36, padx=14).pack(side="right", padx=(0, 8))

        table_wrap = tk.Frame(right, bg=theme.line, highlightthickness=0)
        table_wrap.grid(row=2, column=0, sticky="nsew")
        style_tree(self, theme, fonts)
        columns = ("type", "stem", "stars", "subject", "state")
        self.tree = ttk.Treeview(
            table_wrap,
            columns=columns,
            show="headings",
            style="Quiz.Treeview",
            selectmode="browse",
        )
        headings = {"type": "题型", "stem": "题干", "stars": "难度", "subject": "科目", "state": "状态"}
        widths = {"type": 62, "stem": 320, "stars": 62, "subject": 76, "state": 60}
        for key in columns:
            self.tree.heading(key, text=headings[key])
            self.tree.column(key, width=widths[key], anchor="w" if key == "stem" else "center", stretch=key == "stem")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = dark_scrollbar(table_wrap, theme, self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Configure>", self._fit_columns)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _e: self.edit_question())

        self.footer = tk.Label(
            right,
            text="双击一行可直接编辑 · 修改即时写入题库文件",
            bg=theme.bg,
            fg=theme.text3,
            font=fonts.small,
        )
        self.footer.grid(row=3, column=0, sticky="w", pady=(8, 0))

    # ------------------------------------------------------------ 刷新

    def on_show(self) -> None:
        self.reload_bank_list()
        self.refresh_table()

    def reload_bank_list(self) -> None:
        theme = self.app.theme
        for child in self.rows_holder.winfo_children():
            child.destroy()
        bank = self.app.engine.bank if self.app.engine else None
        active_name = bank.path.name if bank and bank.path else ""
        infos = self.app.storage.bank_infos()
        if not infos:
            tk.Label(
                self.rows_holder,
                text="还没有题库，点下面的「新建」开始",
                bg=theme.bg,
                fg=theme.text3,
                font=self.app.fonts.small,
                wraplength=240,
                justify="left",
            ).pack(anchor="w")
            return
        for info in infos:
            row = BankRow(self.rows_holder, self, info, active=info.filename == active_name)
            row.pack(fill="x", pady=(0, 6))

    def refresh_table(self) -> None:
        if not self.app.engine or not self.app.engine.bank:
            return
        bank = self.app.engine.bank
        theme, fonts = self.app.theme, self.app.fonts
        self.title_label.configure(text=bank.name if len(bank.name) <= 22 else bank.name[:21] + "…")
        enabled = len(bank.active_items())
        self.meta_label.configure(text=f"共 {len(bank.items)} 题 · 启用 {enabled} 题")
        self.dirty_label.configure(text="未保存" if bank.dirty else "")

        raw_keyword = self.keyword_entry.get().strip() if hasattr(self, "keyword_entry") else ""
        keyword = "" if raw_keyword == self.PLACEHOLDER else raw_keyword.lower()
        type_label = self.type_filter.get()
        wanted_type = next((k for k, v in TYPE_LABEL.items() if v == type_label), None)

        self.tree.delete(*self.tree.get_children())
        shown = 0
        for index, question in enumerate(bank.items, start=1):
            if wanted_type and question.type != wanted_type:
                continue
            haystack = " ".join([question.q, *question.a, question.tip, question.subject]).lower()
            if keyword and keyword not in haystack:
                continue
            self.tree.insert(
                "",
                "end",
                iid=question.id,
                values=(
                    TYPE_LABEL.get(question.type, question.type),
                    question.q.replace("\n", " ")[:80],
                    question.stars(),
                    question.subject or "-",
                    "启用" if question.enabled else "暂停",
                ),
            )
            shown += 1
        if self.selected_id and self.tree.exists(self.selected_id):
            self.tree.selection_set(self.selected_id)
        self.footer.configure(text=f"显示 {shown} 题 · 双击一行可直接编辑 · 修改即时写入题库文件")

    def _fit_columns(self, event=None) -> None:
        total = self.tree.winfo_width()
        if total < 120:
            return
        fixed = 62 + 62 + 76 + 60
        self.tree.column("stem", width=max(160, total - fixed - 18))

    def _on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if selection:
            self.selected_id = selection[0]

    # ------------------------------------------------------------ 题库操作

    def _persist(self) -> None:
        engine = self.app.engine
        if not engine or not engine.bank:
            return
        bank = engine.bank
        try:
            bank.save()
            self.dirty_label.configure(text="")
        except OSError as exc:
            messagebox.showerror("保存失败", f"无法写入题库文件：\n{exc}", parent=self)

    def save_bank(self) -> None:
        self._persist()
        self.refresh_table()
        self.reload_bank_list()
        self.app.toast("题库已保存")
        self.app.refresh_status()

    def create_bank(self) -> None:
        name = simpledialog.askstring("新建题库", "题库名称：", parent=self, initialvalue="我的题库")
        if not name:
            return
        path = self.app.storage.unique_bank_path(name)
        bank = Bank(name=name, items=[], path=path)
        try:
            bank.save()
        except OSError as exc:
            messagebox.showerror("创建失败", str(exc), parent=self)
            return
        self._activate(path)
        self.app.toast(f"已创建题库「{name}」，点「新增题目」开始录入")

    def switch_bank(self, info) -> None:
        current = self.app.engine.bank.path if self.app.engine and self.app.engine.bank else None
        if current and Path(current).name == info.filename:
            return
        self._activate(info.path)

    def _activate(self, path: Path) -> None:
        engine = self.app.engine
        if not engine:
            return
        if engine.bank and engine.bank.dirty:
            engine.bank.save()
        if engine.status().get("hasRound"):
            engine.abandon_round()
        try:
            engine.load_bank(path)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            messagebox.showerror("加载失败", f"这个题库文件无法读取：\n{exc}", parent=self)
            return
        self.selected_id = None
        self.reload_bank_list()
        self.refresh_table()
        self.app.refresh_status()

    def rename_bank(self) -> None:
        bank = self.app.engine.bank
        name = simpledialog.askstring("重命名题库", "新的名称：", parent=self, initialvalue=bank.name)
        if not name:
            return
        bank.name = name
        bank.dirty = True
        self._persist()
        self.refresh_table()
        self.reload_bank_list()

    def import_bank(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self,
            title="选择题库 JSON 文件",
            filetypes=[("JSON 题库", "*.json"), ("所有文件", "*.*")],
        )
        if not filename:
            return
        try:
            payload = json.loads(Path(filename).read_text(encoding="utf-8"))
            name, items = Bank.parse_payload(payload)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            messagebox.showerror("导入失败", f"文件不是有效的题库 JSON：\n{exc}", parent=self)
            return
        if not items:
            messagebox.showwarning("导入失败", "文件里没有题目", parent=self)
            return
        merged = messagebox.askyesno(
            "导入方式",
            f"读到 {len(items)} 道题。\n\n是：新建一个题库并切换过去\n否：合并到当前题库",
            parent=self,
        )
        engine = self.app.engine
        if merged:
            path = self.app.storage.unique_bank_path(name)
            bank = Bank(name=name, items=items, path=path)
            bank.save()
            self._activate(path)
        else:
            existing_ids = {q.id for q in engine.bank.items}
            added = 0
            for question in items:
                if question.id in existing_ids:
                    question.id = Question({}).id
                engine.bank.add(question)
                added += 1
            self._persist()
            self.refresh_table()
            self.reload_bank_list()
            self.app.toast(f"已合并 {added} 道题")
        self.app.refresh_status()

    def export_bank(self) -> None:
        bank = self.app.engine.bank
        if not bank.items:
            messagebox.showinfo("导出", "当前题库还是空的", parent=self)
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="导出题库",
            defaultextension=".json",
            initialfile=f"{bank.name}.json",
            filetypes=[("JSON 题库", "*.json")],
        )
        if not filename:
            return
        try:
            bank.export_json(Path(filename))
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self.app.toast(f"已导出到 {Path(filename).name}")

    # ------------------------------------------------------------ 题目操作

    def new_question(self) -> None:
        QuestionDialog(self, self.app, None, self._on_saved)

    def edit_question(self) -> None:
        question = self._current_question()
        if question is None:
            self.app.toast("先选中一行")
            return
        QuestionDialog(self, self.app, question, self._on_saved)

    def _current_question(self) -> Question | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.app.engine.bank.find(selection[0])

    def delete_question(self) -> None:
        question = self._current_question()
        if question is None:
            self.app.toast("先选中一行")
            return
        if not messagebox.askyesno("删除题目", f"确定删除这道题吗？\n\n{question.q[:60]}", parent=self):
            return
        self.app.engine.bank.remove(question.id)
        self.selected_id = None
        self._persist()
        self.refresh_table()
        self.reload_bank_list()
        self.app.toast("已删除")

    def _on_saved(self, question: Question, is_new: bool) -> None:
        bank = self.app.engine.bank
        if is_new:
            bank.add(question)
        else:
            for index, item in enumerate(bank.items):
                if item.id == question.id:
                    bank.items[index] = question
                    break
            else:
                bank.add(question)
        bank.dirty = True
        self.selected_id = question.id
        self._persist()
        self.refresh_table()
        self.reload_bank_list()
        self.app.refresh_status()
        self.app.toast("已保存" if not is_new else "已新增题目")

    def handle_key(self, event) -> bool:
        if event.keysym == "Delete":
            self.delete_question()
            return True
        return False


class QuestionDialog(tk.Toplevel):
    """新增 / 编辑题目的表单。"""

    def __init__(self, parent: BankPage, app, question: Question | None, on_saved):
        super().__init__(parent)
        self.app = app
        self.parent_page = parent
        self.on_saved = on_saved
        self.is_new = question is None
        self.source = question
        self.theme = app.theme
        self.fonts = app.fonts

        self.title("新增题目" if self.is_new else "编辑题目")
        self.configure(bg=self.theme.bg)
        self.type_var = tk.StringVar(value=(question.type if question else "single"))
        dialog_height = 742 if self.type_var.get() == "subjective" else 664
        self.geometry(f"760x{dialog_height}")
        self.minsize(700, 600)
        style_tree(self, self.theme, self.fonts)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self.difficulty = tk.IntVar(value=(question.difficulty if question else 2))
        self.option_vars: list[tk.BooleanVar] = []
        self.option_entries: list[tk.Entry] = []
        self.correct_var = tk.IntVar(value=(question.k if question and question.type != "multiple" else 0))

        self._build()
        self._center()
        self.after(30, lambda: apply_dark_title_bar(self, self.theme.name == "dark"))
        self.bind("<Escape>", lambda _e: self.destroy())

    def _center(self) -> None:
        self.update_idletasks()
        root = self.app
        width, height = self.winfo_width(), self.winfo_height()
        x = root.winfo_rootx() + (root.winfo_width() - width) // 2
        y = root.winfo_rooty() + max(20, (root.winfo_height() - height) // 2)
        self.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------ 构建

    def _build(self) -> None:
        theme, fonts = self.theme, self.fonts
        wrap = tk.Frame(self, bg=theme.bg)
        wrap.pack(fill="both", expand=True, padx=26, pady=20)

        # 按钮固定在底部，内容区在其上方排布
        bottom = tk.Frame(wrap, bg=theme.bg)
        bottom.pack(side="bottom", fill="x", pady=(10, 0))
        self.error_label = tk.Label(bottom, text="", bg=theme.bg, fg=theme.bad, font=self.fonts.small, justify="left")
        self.error_label.pack(anchor="w", pady=(0, 6))
        actions = tk.Frame(bottom, bg=theme.bg)
        actions.pack(fill="x")
        Button(actions, theme, fonts, "取消", self.destroy, kind="ghost", height=42).pack(side="right")
        Button(actions, theme, fonts, "保存题目", self.save, kind="primary", height=42).pack(side="right", padx=(0, 10))

        top = tk.Frame(wrap, bg=theme.bg)
        top.pack(fill="x")
        tk.Label(top, text="题型", bg=theme.bg, fg=theme.text2, font=fonts.body).pack(side="left")
        self.type_box = ttk.Combobox(
            top,
            state="readonly",
            values=tuple(TYPE_LABEL[t] for t in TYPE_ORDER),
            width=12,
            font=(fonts.family, 10),
        )
        self.type_box.set(TYPE_LABEL[self.type_var.get()])
        self.type_box.pack(side="left", padx=(10, 0))
        self.type_box.bind("<<ComboboxSelected>>", self._on_type_change)

        diff = tk.Frame(top, bg=theme.bg)
        diff.pack(side="right")
        tk.Label(diff, text="难度", bg=theme.bg, fg=theme.text2, font=fonts.body).pack(side="left", padx=(0, 8))
        self.star_buttons = []
        for star in range(1, 6):
            button = Button(
                diff,
                theme,
                fonts,
                "★" * star,
                (lambda value=star: self._set_difficulty(value)),
                kind="primary" if star == self.difficulty.get() else "ghost",
                height=32,
                padx=8,
                font=(fonts.family, 9),
            )
            button.pack(side="left", padx=(0, 3))
            self.star_buttons.append(button)

        tk.Label(wrap, text="题干", bg=theme.bg, fg=theme.text2, font=fonts.small).pack(anchor="w", pady=(16, 4))
        self.stem = self._text(wrap, height=3)
        self.stem.pack(fill="x")
        if self.source:
            self.stem.insert("1.0", self.source.q)

        self.answer_area = tk.Frame(wrap, bg=theme.bg)
        self.answer_area.pack(fill="x", pady=(14, 0))
        self._build_answer_area()

        meta = tk.Frame(wrap, bg=theme.bg)
        meta.pack(fill="x", pady=(12, 0))
        tk.Label(meta, text="科目", bg=theme.bg, fg=theme.text2, font=fonts.small).pack(side="left")
        self.subject = self._entry(meta, width=12)
        self.subject.pack(side="left", padx=(8, 20), ipady=5)
        self.subject.insert(0, self.source.subject if self.source else "常识")
        tk.Label(meta, text="年级", bg=theme.bg, fg=theme.text2, font=fonts.small).pack(side="left")
        self.level = self._entry(meta, width=12)
        self.level.pack(side="left", padx=(8, 0), ipady=5)
        if self.source and self.source.level:
            self.level.insert(0, self.source.level)

        tk.Label(wrap, text="解析（可选）", bg=theme.bg, fg=theme.text2, font=fonts.small).pack(anchor="w", pady=(12, 4))
        self.tip = self._text(wrap, height=3)
        # 解析框吃掉底部剩余空间，表单不会在按钮上方空出一大块
        self.tip.pack(fill="both", expand=True)
        if self.source and self.source.tip:
            self.tip.insert("1.0", self.source.tip)



    def _text(self, parent, height: int) -> tk.Text:
        theme = self.theme
        return tk.Text(
            parent,
            height=height,
            bg=theme.surface,
            fg=theme.text,
            insertbackground=theme.text,
            font=(self.fonts.family, 11),
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.line,
            highlightcolor=theme.accent,
            wrap="word",
            padx=10,
            pady=8,
        )

    def _entry(self, parent, width: int = 20) -> tk.Entry:
        theme = self.theme
        return tk.Entry(
            parent,
            width=width,
            bg=theme.surface,
            fg=theme.text,
            insertbackground=theme.text,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.line,
            highlightcolor=theme.accent,
            font=(self.fonts.family, 11),
        )

    def _build_answer_area(self) -> None:
        theme, fonts = self.theme, self.fonts
        for child in self.answer_area.winfo_children():
            child.destroy()
        self.option_vars = []
        self.option_entries = []
        qtype = self.type_var.get()
        source_options = list(self.source.a) if self.source and self.source.a else ["", "", "", ""]
        if qtype == "boolean" and (not source_options or len(source_options) != 2):
            source_options = ["正确", "错误"]

        if qtype in ("single", "multiple", "boolean"):
            header = tk.Frame(self.answer_area, bg=theme.bg)
            header.pack(fill="x")
            tk.Label(
                header,
                text="选项（勾选/点选正确答案）" if qtype != "boolean" else "答案为「正确」或「错误」",
                bg=theme.bg,
                fg=theme.text2,
                font=fonts.small,
            ).pack(side="left")
            if qtype != "boolean":
                Button(
                    header,
                    theme,
                    fonts,
                    "+ 增加选项",
                    self._add_option,
                    kind="quiet",
                    height=28,
                    padx=10,
                    font=fonts.small,
                ).pack(side="right")

            holder = tk.Frame(self.answer_area, bg=theme.bg)
            holder.pack(fill="x", pady=(6, 0))
            for index, text in enumerate(source_options[:8]):
                self._add_option_row(holder, index, text, qtype == "boolean")
            self._option_holder = holder
        elif qtype == "text":
            tk.Label(
                self.answer_area,
                text="可接受的答案（每行一个，忽略大小写与全半角差异）",
                bg=theme.bg,
                fg=theme.text2,
                font=fonts.small,
            ).pack(anchor="w")
            self.answers_text = self._text(self.answer_area, height=3)
            self.answers_text.pack(fill="x", pady=(6, 0))
            if self.source and self.source.answers:
                self.answers_text.insert("1.0", "\n".join(self.source.answers))
        else:
            tk.Label(
                self.answer_area,
                text="参考答案（提交后给孩子对照自评）",
                bg=theme.bg,
                fg=theme.text2,
                font=fonts.small,
            ).pack(anchor="w")
            self.model_text = self._text(self.answer_area, height=3)
            self.model_text.pack(fill="x", pady=(6, 0))
            if self.source and self.source.modelAnswer:
                self.model_text.insert("1.0", self.source.modelAnswer)
            tk.Label(
                self.answer_area, text="评分标准（可选）", bg=theme.bg, fg=theme.text2, font=fonts.small
            ).pack(anchor="w", pady=(10, 0))
            self.rubric_text = self._text(self.answer_area, height=2)
            self.rubric_text.pack(fill="x", pady=(6, 0))
            if self.source and self.source.rubric:
                self.rubric_text.insert("1.0", self.source.rubric)

    def _add_option_row(self, holder: tk.Frame, index: int, text: str, readonly: bool) -> None:
        theme, fonts = self.theme, self.fonts
        row = tk.Frame(holder, bg=theme.bg)
        row.pack(fill="x", pady=2)
        qtype = self.type_var.get()
        if qtype == "multiple":
            var = tk.BooleanVar(
                value=bool(self.source and index in self.source.correctIndices)
            )
            widget = tk.Checkbutton(
                row,
                variable=var,
                bg=theme.bg,
                activebackground=theme.bg,
                selectcolor=theme.surface3,
                highlightthickness=0,
                bd=0,
            )
        else:
            var = tk.BooleanVar(value=False)
            widget = tk.Radiobutton(
                row,
                variable=self.correct_var,
                value=index,
                bg=theme.bg,
                activebackground=theme.bg,
                selectcolor=theme.surface3,
                highlightthickness=0,
                bd=0,
            )
            if self.source and index == self.source.k:
                self.correct_var.set(index)
        widget.pack(side="left")
        tk.Label(row, text=LETTERS[index], bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="left", padx=(0, 6))
        entry = self._entry(row)
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        entry.insert(0, text)
        if readonly:
            entry.configure(state="readonly", readonlybackground=theme.surface2)
        if qtype == "multiple":
            self.option_vars.append(var)
        self.option_entries.append(entry)

    def _add_option(self) -> None:
        index = len(self.option_entries)
        if index >= 8:
            self.app.toast("最多 8 个选项")
            return
        self._add_option_row(self._option_holder, index, "", False)
        self.answer_area.update_idletasks()

    def _on_type_change(self, _event=None) -> None:
        label = self.type_box.get()
        qtype = next((k for k, v in TYPE_LABEL.items() if v == label), "single")
        if qtype == self.type_var.get():
            return
        self._stash_options()
        self.type_var.set(qtype)
        self._build_answer_area()

    def _stash_options(self) -> None:
        """切换题型前把已填的选项文本存回 source，避免丢失。"""
        texts = [entry.get() for entry in self.option_entries]
        if any(texts):
            if self.source is None:
                self.source = Question({"q": "", "type": self.type_var.get()})
            self.source.a = texts
            if self.type_var.get() == "multiple":
                self.source.correctIndices = [i for i, var in enumerate(self.option_vars) if var.get()]
            else:
                self.source.k = self.correct_var.get()

    def _set_difficulty(self, value: int) -> None:
        self.difficulty.set(value)
        for index, button in enumerate(self.star_buttons, start=1):
            button.kind = "primary" if index == value else "ghost"
            button._draw()

    # ------------------------------------------------------------ 保存

    def save(self) -> None:
        qtype = self.type_var.get()
        stem = self.stem.get("1.0", "end").strip()
        tip = self.tip.get("1.0", "end").strip()
        data: dict = {
            "id": self.source.id if self.source else "",
            "type": qtype,
            "q": stem,
            "difficulty": self.difficulty.get(),
            "tip": tip,
            "subject": self.subject.get().strip() or "常识",
            "level": self.level.get().strip(),
            "enabled": True if self.is_new else (self.source.enabled if self.source else True),
        }

        if qtype in ("single", "multiple", "boolean"):
            data["a"] = [entry.get().strip() for entry in self.option_entries]
            if qtype == "multiple":
                data["correctIndices"] = [i for i, var in enumerate(self.option_vars) if var.get()]
            else:
                data["k"] = self.correct_var.get()
        elif qtype == "text":
            data["answers"] = [line.strip() for line in self.answers_text.get("1.0", "end").splitlines() if line.strip()]
        else:
            data["modelAnswer"] = self.model_text.get("1.0", "end").strip()
            data["rubric"] = self.rubric_text.get("1.0", "end").strip()

        if self.source and not self.is_new:
            data["created_at"] = self.source.created_at

        question = Question(data)
        errors = question.validate()
        if errors:
            self.error_label.configure(text="；".join(errors))
            return
        self.on_saved(question, self.is_new)
        self.destroy()
