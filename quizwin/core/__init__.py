"""核心层：题库模型、玩法规则、本地存储与答题引擎。"""

from .engine import Engine, EngineError
from .models import Bank, Question, QUESTION_TYPES, TYPE_LABEL
from .rules import PLAY_MODES, PLAY_MODE_HINT, PLAY_MODE_LABEL, Rules
from .storage import BankInfo, Storage

__all__ = [
    "Engine",
    "EngineError",
    "Bank",
    "Question",
    "QUESTION_TYPES",
    "TYPE_LABEL",
    "Rules",
    "PLAY_MODES",
    "PLAY_MODE_LABEL",
    "PLAY_MODE_HINT",
    "Storage",
    "BankInfo",
]
