"""题库数据模型。

字段与上游项目 StudyOnTV（题了个题）的题库 JSON 完全对齐，便于互相导入导出：

    {"name": "题库名", "version": 2, "items": [ {...}, ... ]}

题目字段：
    id            可选，缺省自动生成 q_xxx
    type          single 单选 / multiple 多选 / boolean 判断 / text 填空 / subjective 主观
    q             题干
    a             选项数组（单选、多选 2-8 个；判断固定 正确 / 错误）
    k             单选答案下标；判断题 0=正确、1=错误
    correctIndices 多选答案下标数组，必须全部选对
    answers       填空可接受答案（忽略大小写、首尾空白、全角半角差异）
    difficulty    1-5 星，默认 2
    tip           解析
    subject       科目，默认「常识」
    level         年级 / 学段
    modelAnswer   主观题参考答案
    rubric        主观题评分标准
    enabled       是否启用（暂停的题不参与抽题）
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Iterable

QUESTION_TYPES = ("single", "multiple", "boolean", "text", "subjective")
TYPE_LABEL = {
    "single": "单选",
    "multiple": "多选",
    "boolean": "判断",
    "text": "填空",
    "subjective": "主观",
}
OBJECTIVE_TYPES = ("single", "multiple", "boolean", "text")
LETTERS = "ABCDEFGH"


def new_id() -> str:
    return "q_" + uuid.uuid4().hex


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip() for v in value]


class Question:
    """单道题目。构造时会做字段规范化，validate() 给出可读的错误列表。"""

    def __init__(self, data: dict | None = None):
        data = dict(data or {})
        self.id = str(data.get("id") or "").strip() or new_id()

        qtype = str(data.get("type") or "single").strip()
        self.type = qtype if qtype in QUESTION_TYPES else "single"

        self.q = str(data.get("q") or "").strip()

        options = _as_str_list(data.get("a"))
        if self.type == "boolean" and not options:
            options = ["正确", "错误"]
        self.a = options

        self.k = _as_int(data.get("k"), 0)
        raw_indices = data.get("correctIndices")
        if isinstance(raw_indices, (list, tuple)):
            self.correctIndices = [_as_int(v, -1) for v in raw_indices]
        else:
            self.correctIndices = [self.k] if self.type in ("single", "boolean") else []

        self.answers = _as_str_list(data.get("answers"))
        self.difficulty = _as_int(data.get("difficulty"), 2)
        self.tip = str(data.get("tip") or "").strip()
        self.subject = str(data.get("subject") or "常识").strip() or "常识"
        self.level = str(data.get("level") or "").strip()
        self.modelAnswer = str(data.get("modelAnswer") or "").strip()
        self.rubric = str(data.get("rubric") or "").strip()
        self.enabled = bool(data.get("enabled", True))
        self.created_at = _as_int(data.get("created_at"), 0)

    # ---------- 判定 ----------

    def expected_indices(self) -> list[int]:
        if self.type == "multiple":
            return sorted(set(self.correctIndices))
        if self.type in ("single", "boolean"):
            return [self.k]
        return []

    def is_objective(self) -> bool:
        return self.type in OBJECTIVE_TYPES

    def correct_text(self) -> str:
        """用于反馈展示的正确答案文本。"""
        if self.type == "text":
            return self.answers[0] if self.answers else ""
        if self.type == "subjective":
            return self.modelAnswer
        parts = []
        for index in self.expected_indices():
            if 0 <= index < len(self.a):
                parts.append(f"{LETTERS[index]}. {self.a[index]}")
        return "　".join(parts)

    def stars(self) -> str:
        return "★" * max(1, min(5, self.difficulty))

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.q:
            errors.append("题干不能为空")
        elif len(self.q) > 5000:
            errors.append("题干不能超过 5000 字")

        if self.type in ("single", "multiple", "boolean"):
            if not 2 <= len(self.a) <= 8:
                errors.append("选项数量需要 2–8 个")
            elif any(not item for item in self.a):
                errors.append("选项不能为空")
            else:
                if self.type == "multiple":
                    if not self.correctIndices:
                        errors.append("请至少选择一个正确答案")
                    elif any(not 0 <= i < len(self.a) for i in self.correctIndices):
                        errors.append("答案序号超出选项范围")
                elif not 0 <= self.k < len(self.a):
                    errors.append("请选择正确答案")
        elif self.type == "text":
            if not [x for x in self.answers if x]:
                errors.append("填空题需要至少一个可接受的答案")
        elif self.type == "subjective":
            if not self.modelAnswer and not self.rubric:
                errors.append("主观题建议填写参考答案或评分标准，便于自评")

        if not 1 <= self.difficulty <= 5:
            errors.append("难度需要为 1–5 星")
        return errors

    # ---------- 序列化 ----------

    def to_dict(self, for_export: bool = True) -> dict:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "q": self.q,
        }
        if self.type in ("single", "multiple", "boolean"):
            data["a"] = list(self.a)
        if self.type == "multiple":
            data["correctIndices"] = list(self.correctIndices)
        elif self.type in ("single", "boolean"):
            data["k"] = self.k
        if self.type == "text":
            data["answers"] = list(self.answers)
        data["difficulty"] = self.difficulty
        if self.tip:
            data["tip"] = self.tip
        if self.subject:
            data["subject"] = self.subject
        if self.level:
            data["level"] = self.level
        if self.type == "subjective":
            if self.modelAnswer:
                data["modelAnswer"] = self.modelAnswer
            if self.rubric:
                data["rubric"] = self.rubric
        if not for_export:
            data["enabled"] = self.enabled
            if self.created_at:
                data["created_at"] = self.created_at
        return data

    def clone(self) -> "Question":
        return Question(self.to_dict(for_export=False))


class Bank:
    """一个题库文件。"""

    def __init__(self, name: str = "未命名题库", items: Iterable[Question] | None = None, path: Path | None = None):
        self.name = name or "未命名题库"
        self.items: list[Question] = list(items or [])
        self.path = Path(path) if path else None
        self.dirty = False

    # ---------- 读取 ----------

    @staticmethod
    def parse_payload(payload: Any) -> tuple[str, list[Question]]:
        """接受三种形态：{name, items}、{questions: [...]}、裸数组。"""
        name = "导入的题库"
        raw_items: Any = payload
        if isinstance(payload, dict):
            name = str(payload.get("name") or payload.get("title") or name)
            raw_items = payload.get("items")
            if raw_items is None:
                raw_items = payload.get("questions")
            if raw_items is None:
                # 单题对象
                raw_items = [payload] if payload.get("q") else []
        if not isinstance(raw_items, list):
            raise ValueError("题库格式不正确：需要 items 数组")
        items = [Question(x) for x in raw_items if isinstance(x, dict)]
        return name, items

    @classmethod
    def load(cls, path: Path) -> "Bank":
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        name, items = cls.parse_payload(payload)
        if isinstance(payload, dict) and payload.get("name"):
            name = str(payload["name"])
        bank = cls(name=name, items=items, path=path)
        bank.dirty = False
        return bank

    # ---------- 写入 ----------

    def to_payload(self) -> dict:
        return {
            "name": self.name,
            "version": 2,
            "items": [q.to_dict() for q in self.items],
        }

    def save(self, path: Path | None = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("题库还没有保存路径")
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_payload(), ensure_ascii=False, indent=2)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        tmp.replace(target)
        self.path = target
        self.dirty = False
        return target

    def export_json(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    # ---------- 维护 ----------

    def subjects(self) -> list[str]:
        return sorted({q.subject for q in self.items if q.subject})

    def levels(self) -> list[str]:
        return sorted({q.level for q in self.items if q.level})

    def active_items(self) -> list[Question]:
        return [q for q in self.items if q.enabled]

    def add(self, question: Question) -> None:
        self.items.append(question)
        self.dirty = True

    def remove(self, question_id: str) -> bool:
        before = len(self.items)
        self.items = [q for q in self.items if q.id != question_id]
        changed = len(self.items) != before
        self.dirty = self.dirty or changed
        return changed

    def find(self, question_id: str) -> Question | None:
        for item in self.items:
            if item.id == question_id:
                return item
        return None
