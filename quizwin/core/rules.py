"""玩法规则：与上游 LocalStore.config() 的字段同名同义，只保留桌面端有意义的项。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PLAY_MODES = ("round", "streak", "practice")
PLAY_MODE_LABEL = {
    "round": "按组闯关",
    "streak": "连续答对",
    "practice": "自由练习",
}
PLAY_MODE_HINT = {
    "round": "做完指定题量并达到正确率，才算通过本组",
    "streak": "连续答对指定题量；答错重新计数",
    "practice": "无限出题，不奖励时长，可偿还加练池",
}

TIME_PATTERN_HINT = "HH:MM"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


@dataclass
class Rules:
    playMode: str = "round"
    questionsPerRound: int = 5
    passRatio: float = 0.6
    sessionMinutes: int = 10
    roundsPerDay: int = 3
    dailyMinutes: int = 60

    extraEnabled: bool = True
    wrongThreshold: int = 3
    extraQuestions: int = 2

    difficultyRewardEnabled: bool = False
    difficultyRewards: dict[str, float] = field(
        default_factory=lambda: {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "5": 5.0}
    )

    spacedRepetitionEnabled: bool = False
    quizSubjects: list[str] = field(default_factory=list)
    quizLevels: list[str] = field(default_factory=list)

    autoNextSeconds: int = 0

    dailyWindowEnabled: bool = False
    windowStart: str = "18:30"
    windowEnd: str = "20:00"

    # ---------- 序列化 ----------

    def to_dict(self) -> dict[str, Any]:
        return {
            "playMode": self.playMode,
            "questionsPerRound": int(self.questionsPerRound),
            "passRatio": round(float(self.passRatio), 4),
            "sessionMinutes": int(self.sessionMinutes),
            "roundsPerDay": int(self.roundsPerDay),
            "dailyMinutes": int(self.dailyMinutes),
            "extraEnabled": bool(self.extraEnabled),
            "wrongThreshold": int(self.wrongThreshold),
            "extraQuestions": int(self.extraQuestions),
            "difficultyRewardEnabled": bool(self.difficultyRewardEnabled),
            "difficultyRewards": {k: float(v) for k, v in self.difficultyRewards.items()},
            "spacedRepetitionEnabled": bool(self.spacedRepetitionEnabled),
            "quizSubjects": list(self.quizSubjects),
            "quizLevels": list(self.quizLevels),
            "autoNextSeconds": int(self.autoNextSeconds),
            "dailyWindowEnabled": bool(self.dailyWindowEnabled),
            "windowStart": self.windowStart,
            "windowEnd": self.windowEnd,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Rules":
        data = dict(data or {})
        rules = cls()
        mode = str(data.get("playMode") or rules.playMode)
        rules.playMode = mode if mode in PLAY_MODES else "round"

        rules.questionsPerRound = _clamp(_int(data.get("questionsPerRound"), 5), 1, 100)
        rules.sessionMinutes = _clamp(_int(data.get("sessionMinutes"), 10), 1, 120)
        rules.roundsPerDay = _clamp(_int(data.get("roundsPerDay"), 3), 1, 100)
        rules.dailyMinutes = _clamp(_int(data.get("dailyMinutes"), 60), 1, 480)
        rules.wrongThreshold = _clamp(_int(data.get("wrongThreshold"), 3), 1, 100)
        rules.extraQuestions = _clamp(_int(data.get("extraQuestions"), 2), 1, 100)
        rules.autoNextSeconds = _clamp(_int(data.get("autoNextSeconds"), 0), 0, 30)

        try:
            ratio = float(data.get("passRatio", 0.6))
        except (TypeError, ValueError):
            ratio = 0.6
        rules.passRatio = min(1.0, max(0.05, ratio))

        for key in ("extraEnabled", "difficultyRewardEnabled", "spacedRepetitionEnabled", "dailyWindowEnabled"):
            if key in data:
                setattr(rules, key, bool(data[key]))

        rewards = data.get("difficultyRewards")
        if isinstance(rewards, dict):
            merged = dict(rules.difficultyRewards)
            for star in ("1", "2", "3", "4", "5"):
                try:
                    value = float(rewards.get(star, merged[star]))
                except (TypeError, ValueError):
                    value = merged[star]
                merged[star] = min(120.0, max(0.1, value))
            rules.difficultyRewards = merged

        for key in ("quizSubjects", "quizLevels"):
            raw = data.get(key)
            if isinstance(raw, list):
                setattr(rules, key, [str(x).strip() for x in raw if str(x).strip()][:50])

        if data.get("windowStart"):
            rules.windowStart = str(data["windowStart"])
        if data.get("windowEnd"):
            rules.windowEnd = str(data["windowEnd"])
        return rules

    # ---------- 派生值 ----------

    def pass_count(self) -> int:
        """本组需要答对的题数（向上取整，与上游 ceil(target * passRatio) 一致）。"""
        import math

        return math.ceil(self.questionsPerRound * self.passRatio)

    def daily_ms(self) -> int:
        return int(self.dailyMinutes) * 60_000

    def clone(self) -> "Rules":
        return Rules.from_dict(self.to_dict())


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def valid_time(text: str) -> bool:
    import re

    if not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", str(text or "")):
        return False
    return True
