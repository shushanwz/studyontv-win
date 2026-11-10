"""自建题库：给 AI 的提示词，以及展示 / 复制它的对话框。

为什么放在程序里而不是文档里：家长多半是先打开程序、发现题不够，才想着加题。
提示词就在手边，复制一次就能让任意大模型按本程序的格式产出题库 JSON。
"""

from __future__ import annotations

import tkinter as tk

from .theme import apply_dark_title_bar
from .widgets import Button, SlimScrollbar

PROMPT = """你是一位资深的中小学教研员兼题库编辑，熟悉中国大陆义务教育与普通高中课程标准。请为我编写一份可直接导入答题程序的题库，输出 JSON。

【输出格式】只输出一个 JSON 对象，前后不要写解释：
{
  "name": "题库名称",
  "version": 2,
  "items": [ 题目… ]
}

每道题的字段：
{
  "type": "single",
  "q": "题干",
  "a": ["选项A", "选项B", "选项C", "选项D"],
  "k": 0,
  "correctIndices": [0, 2],
  "answers": ["可接受答案1", "可接受答案2"],
  "difficulty": 3,
  "tip": "解析：为什么是这个答案",
  "subject": "数学",
  "level": "七年级",
  "enabled": true
}

字段规则：
- type 取 single（单选）/ multiple（多选）/ boolean（判断）/ text（填空）/ subjective（主观）之一
- a：单选、多选、判断必填，2–8 个选项；判断题固定写 ["正确", "错误"]
- k：单选与判断的正确选项下标，从 0 开始
- correctIndices：多选题的正确选项下标数组，必须写全（此时不写 k）
- answers：填空题可接受的等价答案（此时不写 a/k），至少 1 个
- subjective 主观题写 "modelAnswer" 参考答案与 "rubric" 评分要点，不写 a/k
- difficulty：1–5 星；tip：解析，80 字以内，讲清「为什么」；subject 科目，level 年级或学段
- 不要写 id，程序会自动生成

【内容范围】按下面的清单分配题量，覆盖得越广越好：
1. 小学 1–6 年级：语文（字词、成语、古诗、阅读常识）、数学（计算、应用题、几何、单位换算）、
   英语（词汇、时态、日常表达）、科学、道德与法治、安全自护
2. 初中：语文、数学、英语、物理、化学、生物、历史、地理、道德与法治
3. 高中：语文、数学、英语、物理、化学、生物、历史、地理、政治，难度控制在高考基础题与中档题
4. 通识扩展：
   - 生活常识：饮食健康、交通、法律、防灾、气象、日常维修
   - 电脑与网络：硬件、操作系统、办公软件、文件管理、网络安全、隐私保护
   - 人工智能：大模型原理、机器学习、提示词写法、常见误区、AI 伦理
   - 哲学与思想：中外哲学家、经典命题、逻辑谬误、成语典故里的哲理
   - 古文精彩段落：论语、孟子、庄子、史记、唐宋八大家等名段的释义、默写与语境理解
   - 科学技术史、天文与地理常识

【质量红线】
1. 答案唯一且正确；多选题必须给全所有正确项
2. 干扰项要像真的错法，不要一眼假
3. 解析讲清理由，用孩子能读懂的话，不堆术语
4. 不出有争议、已过时、评价真实人物的题
5. 不出重复题，不把同一个知识点换个数字反复考
6. 古诗文以统编教材版本为准
7. 难度分布约为：1 星 10%、2 星 25%、3 星 35%、4 星 20%、5 星 10%

【分批输出】
先给第 1 批 60 题，等我说「继续」再给下一批。每批都是结构完整、可单独保存为一个 json 文件的 items 数组。

【输出前自检】
逐题检查：type 与字段是否匹配；k / correctIndices 是否越界；填空题 answers 是否非空；
解析是否写明；JSON 是否能被标准解析器解析；选择题是否恰好一个（或一组）正确答案。"""

TOPIC_PRESETS: dict[str, str] = {
    "小学全科": "本次重点：小学 1–6 年级语文、数学、英语、科学、道德与法治、安全自护，以课内基础为主，难度 1–3 星。",
    "初中全科": "本次重点：初中语文、数学、英语、物理、化学、生物、历史、地理、道德与法治，贴近中考基础题。",
    "高中全科": "本次重点：高中语文、数学、英语、物理、化学、生物、历史、地理、政治，控制在高考基础与中档题。",
    "电脑与 AI": "本次重点：电脑硬件与操作系统、办公软件、文件管理、网络安全与隐私、人工智能与大模型原理、提示词写法、AI 伦理与常见误区。",
    "哲学语录": "本次重点：中外哲学家与经典命题、逻辑谬误辨识、成语典故中的哲理，每题给出出处，并附一句可背诵的原文。",
    "古文段落": "本次重点：论语、孟子、庄子、史记、唐宋八大家等古文名段的释义、默写与语境理解，以统编教材版本为准。",
}


def build_prompt(topics: list[str] | None = None) -> str:
    """提示词正文；带主题时在末尾追加本次重点。"""
    text = PROMPT
    extra = [TOPIC_PRESETS[name] for name in (topics or []) if name in TOPIC_PRESETS]
    if extra:
        text += "\n\n【本次重点】\n" + "\n".join(extra)
    return text


class BankPromptDialog(tk.Toplevel):
    """展示提示词：可整段复制，也可先追加主题再复制。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.theme = app.theme
        self.fonts = app.fonts
        self.topics: list[str] = []

        self.title("用 AI 自建题库")
        self.configure(bg=self.theme.bg)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        # 别超出屏幕：1366x768 的笔记本上 760 高会被任务栏切掉「复制提示词」
        height = min(720, int(self.winfo_screenheight() * 0.86))
        self.geometry(f"880x{height}")
        self.minsize(720, 520)
        self._build()
        self._center()
        self.after(30, lambda: apply_dark_title_bar(self, self.theme.name == "dark"))
        self.bind("<Escape>", lambda _e: self.destroy())

    def _center(self) -> None:
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - width) // 2
        y = self.app.winfo_rooty() + max(20, (self.app.winfo_height() - height) // 2)
        self.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------ 构建

    def _build(self) -> None:
        theme, fonts = self.theme, self.fonts
        wrap = tk.Frame(self, bg=theme.bg)
        wrap.pack(fill="both", expand=True, padx=28, pady=22)

        bottom = tk.Frame(wrap, bg=theme.bg)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))
        self.copy_button = Button(
            bottom, theme, fonts, "复制提示词", self.copy_prompt, kind="primary", height=44, padx=22
        )
        self.copy_button.pack(side="right")
        Button(bottom, theme, fonts, "关闭", self.destroy, kind="ghost", height=44).pack(side="right", padx=(0, 10))

        tk.Label(wrap, text="用 AI 自建题库", bg=theme.bg, fg=theme.text, font=fonts.h2).pack(anchor="w")
        tk.Label(
            wrap,
            text=(
                "三步：① 把下面的提示词复制给任意大模型（WorkBuddy、DeepSeek、通义、Kimi 都行）；"
                "② 把它输出的内容保存成 UTF-8 的 .json 文件；③ 回到题库页点「导入」，选中这个文件。\n"
                "提示词里已经写好了格式与覆盖范围，可以按需改主题，但不要删掉「输出格式」那一段。"
            ),
            bg=theme.bg,
            fg=theme.text3,
            font=fonts.small,
            justify="left",
            wraplength=800,
        ).pack(anchor="w", pady=(8, 12))

        preset_row = tk.Frame(wrap, bg=theme.bg)
        preset_row.pack(fill="x", pady=(0, 8))
        tk.Label(preset_row, text="加主题：", bg=theme.bg, fg=theme.text3, font=fonts.small).pack(side="left")
        for name in TOPIC_PRESETS:
            Button(
                preset_row,
                theme,
                fonts,
                name,
                (lambda value=name: self.toggle_topic(value)),
                kind="quiet",
                height=30,
                padx=10,
                font=fonts.small,
            ).pack(side="left", padx=(4, 0))

        holder = tk.Frame(wrap, bg=theme.line)
        holder.pack(fill="both", expand=True)
        self.text = tk.Text(
            holder,
            bg=theme.surface,
            fg=theme.text,
            insertbackground=theme.text,
            font=(fonts.family, 10),
            relief="flat",
            wrap="word",
            padx=16,
            pady=14,
            spacing1=1,
            spacing3=3,
        )
        self.text.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        bar = SlimScrollbar(holder, theme, command=self.text.yview, parent_bg=theme.surface, width=10)
        bar.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.text.configure(yscrollcommand=bar.set)
        self.text.insert("1.0", build_prompt())
        self.text.mark_set("insert", "1.0")
        self.text.focus_set()

    # ------------------------------------------------------------ 动作

    def toggle_topic(self, name: str) -> None:
        if name in self.topics:
            self.topics.remove(name)
            self.app.toast(f"已取消「{name}」")
        else:
            self.topics.append(name)
            self.app.toast(f"已加入「{name}」")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", build_prompt(self.topics))

    def copy_prompt(self) -> None:
        text = self.text.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        # 对话框是置顶的，主窗口的 toast 会被它盖住，所以按钮自己给个回执
        self.copy_button.set_text("已复制 ✓")
        self.after(2200, lambda: self.copy_button.set_text("复制提示词"))
        self.app.toast(f"提示词已复制（{len(text)} 字），粘贴给 AI 即可")


def ask(parent, app) -> None:
    BankPromptDialog(parent, app)
