"""本地存储：题库文件与进度状态。

数据目录按 `paths.default_data_dir()` 判定：源码运行在项目内，安装版在
`%LOCALAPPDATA%\\题了个题\\data`，便携版（exe 旁放 portable.flag）在程序目录。
一律不写注册表、不联网。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import paths
from .models import Bank
from .wrongbook import WrongBook

BASE_DIR = paths.app_dir()  # 程序目录（安装后即 exe 所在目录）
DATA_DIR = paths.default_data_dir()
BANKS_DIR = DATA_DIR / "banks"
TRASH_DIR = DATA_DIR / "trash"
STATE_PATH = DATA_DIR / "state.json"

DEFAULT_PARENT: dict[str, Any] = {
    "enabled": True,
    "setupDone": False,
    "password": {},
    "recovery": {"hash": "", "salt": "", "iters": 0, "used": False},
    "failCount": 0,
    "lockUntil": 0,
    "tiers": [10, 15, 20, 25],
    "hardening": {
        "keyboardHook": True,
        "clipCursor": True,
        "watchdog": True,
        "disableTaskMgr": False,
    },
    "banksRequirePassword": True,
    "settingsGraceSeconds": 300,
    "overlay": {"x": -1, "y": -1},
}

DEFAULT_LOCK: dict[str, Any] = {
    "state": "locked",
    "deadlineWall": 0,
    "lastSeenWall": 0,
    "unlockedMinutes": 0,
    "lastUnlockSource": "",
    "tamperCount": 0,
    "abnormalExit": 0,
    "lockCount": 0,
    "lastLockReason": "",
    # None = 本程序没动过系统声音；0/1 = 动过，值为动之前的原始静音状态（见 core/mute.py）
    "muteBefore": None,
}

DEFAULT_STATE: dict[str, Any] = {
    "schema": 2,
    "active_bank": "",
    # 参与出题的题库（文件名）。空列表 = 只用当前打开的题库，与旧行为一致。
    "quiz_banks": [],
    # 用户主动删掉的内置题库：下次启动不再自动补回来
    "banks_removed": [],
    "theme": "dark",
    "rules": {},
    "today": {"day": "", "credit_ms": 0, "used_ms": 0, "rounds_done": 0},
    "extra_pool": 0,
    "wrong_progress": 0,
    "active_round": None,
    "progress": {},
    "history": {},
    "parent": DEFAULT_PARENT,
    "lock": DEFAULT_LOCK,
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str_list(value: Any) -> list[str]:
    """把可能被写坏的列表字段收成干净的字符串列表（去重、保序）。"""
    if not isinstance(value, (list, tuple)):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _deep_fill(default: dict, saved: Any) -> dict:
    """用默认值补齐缺失字段：一层字典合并，够用且不会把未知字段丢掉。"""
    result = json.loads(json.dumps(default))
    if not isinstance(saved, dict):
        return result
    for key, value in saved.items():
        base = result.get(key)
        if isinstance(base, dict) and isinstance(value, dict):
            result[key] = _deep_fill(base, value)
        else:
            result[key] = value
    return result


def today_key() -> str:
    return date.today().isoformat()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class BankInfo:
    __slots__ = ("name", "path", "count")

    def __init__(self, name: str, path: Path, count: int):
        self.name = name
        self.path = path
        self.count = count

    @property
    def filename(self) -> str:
        return self.path.name

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"BankInfo({self.name!r}, {self.count})"


class Storage:
    def __init__(self, data_dir: Path | None = None, seed: bool = True):
        if data_dir is None:
            data_dir = paths.default_data_dir()
        self.data_dir = Path(data_dir)
        self.banks_dir = self.data_dir / "banks"
        self.trash_dir = self.data_dir / "trash"
        self.state_path = self.data_dir / "state.json"
        self.banks_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, Any] = self._load_state()
        # 状态先读出来，才知道哪些内置题库被用户主动删过；再补缺失的内置题库
        self.seeded = self.ensure_builtin() if seed else []
        self._wrong_book: WrongBook | None = None

    # ---------------- 错题库 ----------------

    @property
    def wrong_book(self) -> WrongBook:
        """错题库的读写入口。懒建：没有错题时不产生空文件。"""
        if self._wrong_book is None:
            self._wrong_book = WrongBook(self)
        return self._wrong_book

    # ---------------- 状态 ----------------

    def _load_state(self) -> dict[str, Any]:
        state = json.loads(json.dumps(DEFAULT_STATE))
        if self.state_path.exists():
            try:
                saved = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    for key, value in saved.items():
                        default = DEFAULT_STATE.get(key)
                        if isinstance(default, dict):
                            # 结构型字段：损坏成非字典时保留默认值，不让脏数据进内存
                            state[key] = _deep_fill(default, value if isinstance(value, dict) else {})
                        else:
                            state[key] = value
            except (json.JSONDecodeError, OSError):
                # 状态文件损坏不应阻止程序启动：保留原文件另存一份，再用默认值
                try:
                    broken = self.state_path.with_suffix(".broken.json")
                    shutil.copyfile(self.state_path, broken)
                except OSError:
                    pass
        # 老文件的 schema 号不再回写：结构已经按新版补齐，标记成新版即可
        state["schema"] = _safe_int(DEFAULT_STATE.get("schema"), 2)
        today = state.setdefault("today", {})
        if not isinstance(today, dict):
            today = {"day": "", "credit_ms": 0, "used_ms": 0, "rounds_done": 0}
            state["today"] = today
        state["today"] = {
            "day": str(today.get("day") or ""),
            "credit_ms": _safe_int(today.get("credit_ms")),
            "used_ms": _safe_int(today.get("used_ms")),
            "rounds_done": _safe_int(today.get("rounds_done")),
        }
        state.setdefault("history", {})
        state.setdefault("progress", {})
        state["quiz_banks"] = _str_list(state.get("quiz_banks"))
        state["banks_removed"] = _str_list(state.get("banks_removed"))
        return state

    def save_state(self) -> None:
        _atomic_write(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=2) + "\n")

    def roll_day(self) -> bool:
        """跨天时重置当日额度，返回是否发生了重置。"""
        today = self.state["today"]
        key = today_key()
        if today.get("day") == key:
            return False
        today["day"] = key
        today["credit_ms"] = 0
        today["used_ms"] = 0
        today["rounds_done"] = 0
        self.save_state()
        return True

    # ---------------- 题库 ----------------

    def bank_infos(self) -> list[BankInfo]:
        infos: list[BankInfo] = []
        for path in sorted(self.banks_dir.glob("*.json")):
            name, count = path.stem, 0
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    name = str(payload.get("name") or path.stem)
                    items = payload.get("items")
                    count = len(items) if isinstance(items, list) else 0
                elif isinstance(payload, list):
                    count = len(payload)
                    name = path.stem
            except (json.JSONDecodeError, OSError):
                count = -1
            infos.append(BankInfo(name, path, count))
        return infos

    def load_bank(self, path: Path) -> Bank:
        return Bank.load(Path(path))

    def load_active_bank(self) -> Bank:
        path = self.active_bank_path()
        if path is None:
            raise FileNotFoundError("data/banks 下没有可用的题库文件")
        return self.load_bank(path)

    def active_bank_path(self) -> Path | None:
        infos = self.bank_infos()
        if not infos:
            return None
        active = str(self.state.get("active_bank") or "")
        for info in infos:
            if info.filename == active:
                return info.path
        return infos[0].path

    def set_active_bank(self, filename: str) -> None:
        self.state["active_bank"] = filename
        self.save_state()

    def unique_bank_path(self, name: str) -> Path:
        safe = "".join(ch for ch in name if ch not in '\\/:*?"<>|').strip() or "题库"
        safe = safe.replace(" ", "-")
        candidate = self.banks_dir / f"{safe}.json"
        index = 2
        while candidate.exists():
            candidate = self.banks_dir / f"{safe}-{index}.json"
            index += 1
        return candidate

    def retire_bank(self, path: Path) -> Path:
        """把题库移入 data/trash，避免误删不可恢复。"""
        target = self.trash_dir / f"{path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}"
        shutil.move(str(path), str(target))
        return target

    # ---------------- 内置题库 ----------------

    def builtin_names(self) -> set[str]:
        return {item.name for item in paths.builtin_bank_files()}

    def is_builtin(self, path: Path) -> bool:
        return Path(path).name in self.builtin_names()

    def ensure_builtin(self) -> list[str]:
        """补齐被删/缺失的内置题库，跳过用户主动删过的那些。"""
        return paths.restore_builtin(self.banks_dir, skip=set(self.state.get("banks_removed") or []))

    def restore_builtin(self) -> list[str]:
        """家长显式要求：把内置题库全部找回来。"""
        self.state["banks_removed"] = []
        created = paths.restore_builtin(self.banks_dir)
        self.save_state()
        return created

    def delete_bank(self, path: Path) -> Path:
        """删除一份题库：移入回收站、记录被删的内置题库、修正出题范围与活跃题库。"""
        path = Path(path)
        name = path.name
        target = self.retire_bank(path)
        self.wrong_book.invalidate()
        if self.is_builtin(path):
            removed = _str_list(self.state.get("banks_removed"))
            if name not in removed:
                removed.append(name)
            self.state["banks_removed"] = removed
        self.state["quiz_banks"] = [x for x in _str_list(self.state.get("quiz_banks")) if x != name]
        if str(self.state.get("active_bank") or "") == name:
            rest = self.bank_infos()
            self.state["active_bank"] = rest[0].filename if rest else ""
        self.save_state()
        return target

    # ---------------- 出题范围 ----------------

    def selected_banks(self) -> list[str]:
        """参与出题的题库文件名；空列表表示「只用当前打开的这一份」。"""
        existing = {info.filename for info in self.bank_infos()}
        return [name for name in (self.state.get("quiz_banks") or []) if name in existing]

    def set_bank_selected(self, filename: str, selected: bool) -> None:
        current = _str_list(self.state.get("quiz_banks"))
        if selected:
            if not current:
                # 空集合的语义是「只有当前打开的那一份」。要加入第二份时，先把
                # 当前这份显式写进去，否则会变成「只剩新加的那一份」。
                active = str(self.state.get("active_bank") or "").strip()
                if active:
                    current = [active]
            if filename not in current:
                current.append(filename)
        else:
            current = [x for x in current if x != filename]
        self.state["quiz_banks"] = current
        self.save_state()

    def select_all_banks(self) -> list[str]:
        names = [info.filename for info in self.bank_infos()]
        self.state["quiz_banks"] = names
        self.save_state()
        return names

    def select_only_bank(self, filename: str) -> list[str]:
        self.state["quiz_banks"] = [filename] if filename else []
        self.save_state()
        return list(self.state["quiz_banks"])

    # ---------------- 历史 ----------------

    def history_bump(self, answered: int = 0, correct: int = 0, rounds: int = 0, used_ms: int = 0) -> None:
        history = self.state.setdefault("history", {})
        key = today_key()
        entry = history.setdefault(key, {"answered": 0, "correct": 0, "rounds": 0, "used_ms": 0})
        entry["answered"] = int(entry.get("answered", 0)) + answered
        entry["correct"] = int(entry.get("correct", 0)) + correct
        entry["rounds"] = int(entry.get("rounds", 0)) + rounds
        entry["used_ms"] = int(entry.get("used_ms", 0)) + used_ms
        # 只保留最近 60 天
        if len(history) > 60:
            keep = sorted(history)[-60:]
            self.state["history"] = {k: history[k] for k in keep}

    def recent_history(self, days: int = 7) -> list[dict]:
        history = self.state.get("history", {})
        rows = []
        for offset in range(days):
            day = (date.today() - timedelta(days=offset)).isoformat()
            entry = history.get(day, {})
            rows.append(
                {
                    "day": day,
                    "label": "今天" if offset == 0 else ("昨天" if offset == 1 else day[5:]),
                    "answered": int(entry.get("answered", 0)),
                    "correct": int(entry.get("correct", 0)),
                    "rounds": int(entry.get("rounds", 0)),
                    "used_minutes": round(int(entry.get("used_ms", 0)) / 60000, 1),
                }
            )
        return rows
