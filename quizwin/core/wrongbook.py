"""错题库：把答错的题自动收进一份独立题库。

设计取舍（都是为了少一层看不懂的东西）：
  * 落成一个普通题库文件 `banks/错题库.json`，题库页能像别的题库一样打开、
    编辑、导出、删除——不需要第二套数据结构，也不用另写一套界面；
  * 去重靠内容指纹（题型 + 题干 + 选项 + 答案），不靠 id：同一道题从不同题库
    抄进来时 id 可能一样也可能不一样，但内容一样就该算同一道题；
  * 答对不移除。用户的诉求是「全部收集」，把移除权交回给人（清空按钮、删单题、
    关掉参与出题的开关），程序不替人判断「这题你学会了」。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .models import Bank, Question

WRONG_FILE = "错题库.json"
WRONG_NAME = "错题库"


def fingerprint(question: Question) -> str:
    """题目的内容指纹：只取「这道题问什么、答案是什么」，与 id、顺序无关。"""
    payload = {
        "type": question.type,
        "q": question.q.strip(),
        "a": [item.strip() for item in question.a],
        "k": question.k if question.type in ("single", "boolean") else None,
        "correctIndices": sorted(set(question.correctIndices)) if question.type == "multiple" else None,
        "answers": [item.strip().lower() for item in question.answers],
        "modelAnswer": question.modelAnswer.strip(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class WrongBook:
    """错题库的读写。带 mtime 缓存：连错十题也只解析一次文件。"""

    def __init__(self, storage):
        self.st = storage
        self._bank: Bank | None = None
        self._prints: set[str] = set()
        self._mtime: float = -1.0
        self._loaded = False

    # ---------------- 路径与状态 ----------------

    @property
    def path(self) -> Path:
        return Path(self.st.banks_dir) / WRONG_FILE

    def exists(self) -> bool:
        return self.path.exists()

    def invalidate(self) -> None:
        """别处改过文件（编辑器里清空、导入覆盖）后调用，丢掉缓存。"""
        self._bank = None
        self._prints = set()
        self._mtime = -1.0
        self._loaded = False

    def bank(self) -> Bank | None:
        """读错题库；文件不存在返回 None。文件改过就重新解析。"""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self.invalidate()
            return None
        if self._loaded and mtime == self._mtime and self._bank is not None:
            return self._bank
        try:
            bank = Bank.load(self.path)
        except (json.JSONDecodeError, OSError, ValueError):
            # 文件坏了：不删人的东西，原地当成空本子，下次收录会整体重写
            bank = Bank(name=WRONG_NAME, items=[], path=self.path)
        self._bank = bank
        self._prints = {fingerprint(item) for item in bank.items}
        self._mtime = mtime
        self._loaded = True
        return bank

    def count(self) -> int:
        bank = self.bank()
        return len(bank.items) if bank else 0

    def contains(self, question: Question) -> bool:
        self.bank()
        return fingerprint(question) in self._prints

    # ---------------- 写入 ----------------

    def add(self, question: Question, prefer: Bank | None = None) -> dict:
        """收进错题库。

        prefer：界面上正开着的那份银行对象。传进来就写它，避免「内存里那份
        改过没保存」被磁盘上的旧内容顶掉；不传就按文件当前内容追加。

        返回 {"added": 是否新增, "created": 是否新建了文件, "total": 现有题数}。
        """
        target = prefer if prefer is not None else self.bank()
        created = False
        if target is None:
            target = Bank(name=WRONG_NAME, items=[], path=self.path)
            created = True

        stamps = {fingerprint(item) for item in target.items}
        stamp = fingerprint(question)
        if stamp in stamps:
            return {"added": False, "created": created, "total": len(target.items)}

        copy = question.clone()
        copy.enabled = True
        copy.created_at = copy.created_at or int(time.time() * 1000)
        target.name = target.name or WRONG_NAME
        target.items.append(copy)
        try:
            target.save(self.path)
        except OSError:
            target.items.pop()
            return {"added": False, "created": created, "total": len(target.items)}

        self._bank = target
        self._prints = stamps | {stamp}
        self._loaded = True
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime = -1.0
        return {"added": True, "created": created, "total": len(target.items)}

    def clear(self) -> int:
        """清空（保留文件本身，题库页里那一行不会消失）。返回清掉的题数。"""
        bank = self.bank()
        if bank is None or not bank.items:
            return 0
        removed = len(bank.items)
        bank.items = []
        try:
            bank.save(self.path)
        except OSError:
            return 0
        self._bank = bank
        self._prints = set()
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime = -1.0
        return removed
