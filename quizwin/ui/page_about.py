"""关于页：玩法说明、快捷键、使用记录与项目出处。"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from .widgets import Button, ScrollFrame

SHORTCUTS = [
    ("A – H / 1 – 8", "选择对应选项（单选直接提交）"),
    ("↑ ↓ ← →", "移动高亮选项"),
    ("Enter / 空格", "确认；单选题提交高亮项，多选题确认所选"),
    ("Ctrl + Enter", "在填空 / 主观题输入框中提交"),
    ("Esc", "返回开始页 / 结束使用计时"),
    ("鼠标点击", "直接选择选项、点击按钮"),
]

GAMEPLAY = [
    ("按组闯关", "做完本组题量并达到正确率才算通过；答错过多会触发加练题，清完加练池才结算。"),
    ("连续答对", "连续答对指定题量才算通过；答错会清零连续数，也会清掉本段已累计的星级奖励。"),
    ("自由练习", "无限出题，不发放使用时长，但可以逐道偿还加练池。"),
    ("加练池", "累计答错达到阈值就增加待做加练题，跨天、重启都保留；答对加练题逐道抵扣。"),
    ("星级奖励", "题目难度 1–5 星，可分别设置答对一题奖励多少分钟；不开启则按每组固定时长发放。"),
    ("每日额度", "每天最多可用的时长与最多组数会限制奖励累加，零点重置，加练池不清零。"),
]


class AboutPage(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        super().__init__(master, bg=app.theme.bg)
        self.app = app
        self._build()

    def on_show(self) -> None:
        self._build()

    def _build(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        theme, fonts = self.app.theme, self.app.fonts
        scroll = ScrollFrame(self, theme, parent_bg=theme.bg)
        scroll.pack(fill="both", expand=True, padx=46, pady=22)
        body = scroll.body

        tk.Label(body, text="关于「题了个题 · 桌面版」", bg=theme.bg, fg=theme.text, font=fonts.h1).pack(anchor="w")
        tk.Label(
            body,
            text="先学再看 · 把电视端的答题解锁玩法搬到 Windows 电脑上",
            bg=theme.bg,
            fg=theme.text2,
            font=fonts.body,
        ).pack(anchor="w", pady=(8, 0))

        self._card(
            body,
            "来源与许可",
            "本程序是对开源项目 StudyOnTV（题了个题，作者 chadyi）电视端实现的 Windows 桌面化复刻，"
            "题库 JSON 格式、玩法判定、加练池与星级奖励规则均以上游实现为准。\n"
            "上游项目仅供个人家庭使用，禁止商业用途与二次分发；本程序同样遵循该约定。\n"
            "源码地址：https://github.com/chadyi/StudyOnTV",
        )

        self._card(
            body,
            "核心玩法",
            "\n".join(f"· {name}：{text}" for name, text in GAMEPLAY),
        )

        self._card(
            body,
            "与电视端的差异",
            "· 遥控器方向键 → 键盘方向键 / 鼠标；OK 确认 → Enter 或点击。\n"
            "· 电视端会拦截第三方视频应用；电脑版不锁定系统、不注入其它程序，"
            "解锁时长改为在本程序里的「使用计时」倒计时消耗。\n"
            "· 主观题没有家长 / AI 批改通道，改为提交后对照参考答案自评（对应上游的 verdict 参数）。\n"
            "· 家庭管理面板、局域网扫码、AI 批改与防卸载属于 Android 端能力，桌面版未包含。",
        )

        shortcut_rows = "\n".join(f"{key}　　{desc}" for key, desc in SHORTCUTS)
        self._card(body, "快捷键", shortcut_rows)

        self._history_card(body)

        data_dir = Path(__file__).resolve().parents[2] / "data"
        self._card(
            body,
            "数据位置",
            f"题库：{data_dir / 'banks'}\n"
            f"规则与进度：{data_dir / 'state.json'}\n"
            "全部数据都在本地，拷贝整个程序文件夹即可迁移；程序不联网。",
        )

        actions = tk.Frame(body, bg=theme.bg)
        actions.pack(fill="x", pady=(20, 12))
        Button(actions, theme, fonts, "打开数据文件夹", self.open_data_folder, height=40).pack(side="left")
        Button(actions, theme, fonts, "导出题库", lambda: self.app.set_page("bank"), kind="quiet", height=40).pack(
            side="left", padx=(10, 0)
        )

    def _card(self, parent, title: str, content: str) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        card = tk.Frame(parent, bg=theme.surface, highlightbackground=theme.line, highlightthickness=1)
        card.pack(fill="x", pady=(18, 0))
        inner = tk.Frame(card, bg=theme.surface)
        inner.pack(fill="x", padx=22, pady=18)
        tk.Label(inner, text=title, bg=theme.surface, fg=theme.text, font=fonts.h3).pack(anchor="w")
        tk.Label(
            inner,
            text=content,
            bg=theme.surface,
            fg=theme.text2,
            font=fonts.body,
            justify="left",
            anchor="w",
            wraplength=980,
        ).pack(anchor="w", pady=(8, 0))

    def _history_card(self, parent) -> None:
        theme, fonts = self.app.theme, self.app.fonts
        card = tk.Frame(parent, bg=theme.surface, highlightbackground=theme.line, highlightthickness=1)
        card.pack(fill="x", pady=(18, 0))
        inner = tk.Frame(card, bg=theme.surface)
        inner.pack(fill="x", padx=22, pady=18)
        tk.Label(inner, text="最近 7 天", bg=theme.surface, fg=theme.text, font=fonts.h3).pack(anchor="w")

        rows = self.app.storage.recent_history(7) if self.app.storage else []
        table = tk.Frame(inner, bg=theme.surface)
        table.pack(anchor="w", pady=(10, 0))
        headers = ("日期", "答题", "答对", "正确率", "完成组数", "使用时长")
        for column, text in enumerate(headers):
            tk.Label(table, text=text, bg=theme.surface, fg=theme.text3, font=fonts.small).grid(
                row=0, column=column, sticky="w", padx=(0, 34)
            )
        for row_index, row in enumerate(rows, start=1):
            accuracy = f"{int(row['correct'] * 100 / row['answered'])}%" if row["answered"] else "-"
            values = (
                row["label"],
                str(row["answered"]),
                str(row["correct"]),
                accuracy,
                str(row["rounds"]),
                f"{row['used_minutes']:g} 分钟",
            )
            for column, text in enumerate(values):
                tk.Label(
                    table,
                    text=text,
                    bg=theme.surface,
                    fg=theme.text if column == 0 else theme.text2,
                    font=fonts.body if column == 0 else fonts.small,
                ).grid(row=row_index, column=column, sticky="w", padx=(0, 34), pady=(6, 0))

    def open_data_folder(self) -> None:
        import os
        import subprocess

        data_dir = Path(__file__).resolve().parents[2] / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(data_dir))  # type: ignore[attr-defined]
        except AttributeError:
            subprocess.Popen(["xdg-open", str(data_dir)])
        except OSError as exc:
            self.app.toast(f"打不开文件夹：{exc}")

    def handle_key(self, event) -> bool:
        return False
