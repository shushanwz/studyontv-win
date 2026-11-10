"""答题引擎。

逻辑对齐上游 StudyOnTV 的 LearningEngine.kt：
  * 三种玩法（round / streak / practice）与完成判定
  * 加练池：累计答错达阈值增加待做题，答对加练题逐道扣除
  * 星级奖励：按题目难度累加，仍受每日额度约束
  * 间隔重复：SM-2 简化算法
  * 每日额度与每日组数上限

与上游的差异（桌面端没有「被管控的应用」这一层）：
  * 解锁时长不再用于限制第三方应用，而是进入「使用计时」页倒计时消耗；
  * 主观题没有家长 / AI 批改通道，改为提交后对照参考答案自评（上游的 verdict 参数即此用途）。
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Bank, Question
from .rules import PLAY_MODES, Rules
from .storage import Storage
from .wrongbook import WRONG_FILE, fingerprint


class EngineError(Exception):
    pass


def normalize_answer(value: str) -> str:
    """NFKC 归一化 + 小写 + 压缩空白，与上游 normalize() 一致。"""
    text = unicodedata.normalize("NFKC", str(value or "").strip()).lower()
    return re.sub(r"\s+", " ", text)


def rules_signature(rules: Rules) -> str:
    raw = json.dumps(rules.to_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _now_ms() -> int:
    return int(time.time() * 1000)


class Engine:
    def __init__(self, storage: Storage):
        self.st = storage
        self.bank: Bank | None = None
        # 出题范围内的其他题库：按「路径 → (mtime, 题目列表)」缓存，改过的文件会自动失效
        self._bank_cache: dict[str, tuple[float, list[Question]]] = {}
        self.load_bank()

    # ---------------------------------------------------------------- 题库

    def load_bank(self, path=None) -> Bank:
        if path is None:
            path = self.st.active_bank_path()
        if path is None:
            raise EngineError("data/banks 下没有题库文件")
        self.bank = self.st.load_bank(path)
        self.st.set_active_bank(self.bank.path.name)
        return self.bank

    def bank_info(self) -> dict:
        if not self.bank:
            return {"name": "（无题库）", "count": 0, "path": None}
        return {
            "name": self.bank.name,
            "count": len(self.bank.items),
            "enabled": len(self.bank.active_items()),
            "path": str(self.bank.path) if self.bank.path else None,
        }

    def pool(self, rules: Rules | None = None) -> list[Question]:
        """出题池：选中题库里所有启用的题，按规则里的科目 / 年级再筛一遍。

        未勾选任何题库时退回「只用当前打开的这一份」，保证旧数据行为不变。
        """
        rules = rules or self.rules()
        items: list[Question] = []
        seen: set[str] = set()
        seen_prints: set[str] = set()
        for path in self.quiz_paths():
            for question in self._bank_items(path):
                if not question.enabled:
                    continue
                if rules.quizSubjects and question.subject not in rules.quizSubjects:
                    continue
                if rules.quizLevels and question.level not in rules.quizLevels:
                    continue
                if question.id in seen:
                    # 复制出来的题库会带着同样的题目 id，撞了会让间隔重复的进度串题
                    question = Question(question.to_dict(for_export=False))
                    question.id = f"{Path(path).stem}#{question.id}"
                    if question.id in seen:
                        continue
                # 内容指纹去重：错题库里存的就是题库里那道题的副本，两边都参与出题时
                # 不能当成两道题——否则同一轮里可能连着出同一题
                stamp = fingerprint(question)
                if stamp in seen_prints:
                    continue
                seen.add(question.id)
                seen_prints.add(stamp)
                items.append(question)
        return items

    def quiz_paths(self) -> list[Path]:
        """参与出题的题库文件路径。"""
        names = self.st.selected_banks()
        infos = {info.filename: info.path for info in self.st.bank_infos()}
        if not names:
            path = self.bank.path if self.bank else None
            return [Path(path)] if path else []
        return [infos[name] for name in names if name in infos]

    def _bank_items(self, path: Path) -> list[Question]:
        path = Path(path)
        # 当前编辑中的题库用内存对象，避免刚改的题还没落盘就抽不到
        if self.bank and self.bank.path and Path(self.bank.path) == path:
            return self.bank.items
        key = str(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return []
        cached = self._bank_cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            bank = self.st.load_bank(path)
            items = bank.items
        except (json.JSONDecodeError, OSError, ValueError):
            items = []
        self._bank_cache[key] = (mtime, items)
        return items

    def quiz_scope(self) -> dict:
        """给界面用：参与出题的份数、可用题数、是否跨库。"""
        paths = self.quiz_paths()
        return {
            "banks": len(paths),
            "pool": len(self.pool()),
            "mixed": len(paths) > 1,
            "names": [Path(p).name for p in paths],
        }

    # ---------------------------------------------------------------- 规则

    def rules(self) -> Rules:
        return Rules.from_dict(self.st.state.get("rules") or {})

    def save_rules(self, rules: Rules) -> None:
        self.st.state["rules"] = rules.to_dict()
        self.st.save_state()

    # ---------------------------------------------------------------- 状态

    def _in_window(self, rules: Rules) -> bool:
        if not rules.dailyWindowEnabled:
            return True
        now = datetime.now()
        current = now.hour * 60 + now.minute
        start = self._minutes(rules.windowStart)
        end = self._minutes(rules.windowEnd)
        if start is None or end is None or start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    @staticmethod
    def _minutes(text: str) -> int | None:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(text or ""))
        if not match:
            return None
        hour, minute = int(match.group(1)), int(match.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour * 60 + minute

    def _next_window_start(self, rules: Rules) -> int:
        start = self._minutes(rules.windowStart)
        now = datetime.now()
        if start is None:
            return int((now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        candidate = now.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return int(candidate.timestamp() * 1000)

    def _next_midnight(self) -> int:
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int(tomorrow.timestamp() * 1000)

    def status(self) -> dict:
        self.st.roll_day()
        rules = self.rules()
        today = self.st.state["today"]
        credit = int(today.get("credit_ms") or 0)
        used = int(today.get("used_ms") or 0)
        rounds = int(today.get("rounds_done") or 0)
        extra_pool = int(self.st.state.get("extra_pool") or 0)
        wrong = int(self.st.state.get("wrong_progress") or 0)

        reason = ""
        next_at = 0
        if used >= rules.daily_ms():
            reason = "quota"
            next_at = self._next_midnight()
        elif not self._in_window(rules):
            reason = "schedule"
            next_at = self._next_window_start(rules)
        elif rounds >= rules.roundsPerDay and credit <= 0:
            reason = "rounds"
            next_at = self._next_midnight()
        elif rounds >= rules.roundsPerDay:
            reason = ""
        elif credit > 0:
            reason = ""
        else:
            reason = "timeup"

        round_ = self.st.state.get("active_round")
        return {
            "remainingSeconds": max(0, credit // 1000),
            "remainingMinutes": round(credit / 60000, 1),
            "usedMinutes": round(used / 60000, 1),
            "dailyMinutes": rules.dailyMinutes,
            "creditMs": credit,
            "extraPool": extra_pool,
            "wrongProgress": wrong,
            "roundsDoneToday": rounds,
            "roundsLeft": max(0, rules.roundsPerDay - rounds),
            "passCount": rules.pass_count(),
            "reason": reason,
            "nextAvailableAt": next_at,
            "hasRound": bool(round_),
            "mode": rules.playMode,
        }

    def status_text(self) -> str:
        st = self.status()
        rules = self.rules()
        if st["reason"] == "quota":
            return "今天的使用时间已用完"
        if st["reason"] == "rounds":
            return "今天的任务已全部完成"
        if st["reason"] == "schedule":
            return "不在可用时段"
        parts = []
        if st["remainingMinutes"] > 0:
            parts.append(f"可用 {self._fmt_minutes(st['remainingMinutes'])}")
        if rules.playMode != "practice":
            parts.append(f"还剩 {st['roundsLeft']} 组")
        if st["extraPool"] > 0:
            parts.append(f"加练池 {st['extraPool']} 题")
        return " · ".join(parts) if parts else "可以开始答题"

    @staticmethod
    def _fmt_minutes(minutes: float) -> str:
        if minutes >= 60:
            hour = int(minutes // 60)
            rest = int(round(minutes % 60))
            return f"{hour} 小时" + (f" {rest} 分" if rest else "")
        return f"{int(round(minutes))} 分钟"

    # ---------------------------------------------------------------- 开始

    def start(self) -> dict:
        status = self.status()
        rules = self.rules()

        if not self.quiz_paths():
            raise EngineError("还没有题库，请先在「题库」里新建或导入")

        if rules.playMode != "practice" and status["reason"] in ("quota", "rounds", "schedule"):
            return {"blocked": status["reason"], "status": status}

        if not self.pool(rules):
            raise EngineError("当前答题范围没有题目，请检查题库科目 / 年级筛选，或调整题库内容")

        signature = rules_signature(rules)
        round_ = self.st.state.get("active_round")

        # 玩法切换：开始对应的新任务，加练池不清零（与上游一致）
        if round_ and round_.get("mode") != rules.playMode:
            round_ = None
        # 规则在开始时固定；一题未答时可直接套用新规则
        if round_ and int(round_.get("answered", 0)) == 0 and round_.get("rules_sig") != signature:
            round_ = None

        if round_ is None:
            round_ = {
                "id": uuid.uuid4().hex,
                "mode": rules.playMode,
                "target": max(1, int(rules.questionsPerRound)),
                "answered": 0,
                "correct": 0,
                "streak": 0,
                "earnedMs": 0,
                "rules": rules.to_dict(),
                "rules_sig": signature,
                "extra": False,
                "pending": False,
                "startedAt": _now_ms(),
            }
            self._next_question(round_, rules)
            self.st.state["active_round"] = round_
            self.st.save_state()

        # 上次提交的主观题还在等自评：恢复自评页，而不是重新出题
        if round_.get("pending"):
            question = Question(round_.get("question") or {})
            public = self._public(round_)
            return {
                "pending_self": True,
                "resumed": True,
                "modelAnswer": question.modelAnswer,
                "rubric": question.rubric,
                "tip": question.tip,
                "question": public["question"],
                "status": public["status"],
            }

        return self._public(round_)

    # ---------------------------------------------------------------- 抽题

    def _next_question(self, round_: dict, rules: Rules) -> None:
        pool = self.pool(rules)
        if not pool:
            raise EngineError("当前答题范围没有题目")

        last_id = (round_.get("question") or {}).get("id")
        progress = self.st.state.get("progress") or {}

        if rules.spacedRepetitionEnabled:
            now = _now_ms()

            def sort_key(q: Question):
                record = progress.get(q.id)
                if record and int(record.get("due_at", 0)) <= now:
                    return (0, int(record.get("due_at", 0)), random.random())
                if not record:
                    return (1, 0, random.random())
                return (2, int(record.get("due_at", 0)), random.random())

            pool = sorted(pool, key=sort_key)
        else:
            pool = list(pool)
            random.shuffle(pool)

        pick = pool[0]
        for candidate in pool:
            if candidate.id != last_id:
                pick = candidate
                break

        round_["question"] = pick.to_dict(for_export=False)
        round_["nonce"] = uuid.uuid4().hex
        extra_enabled = bool((round_.get("rules") or {}).get("extraEnabled", True))
        if round_.get("mode") == "practice":
            round_["extra"] = int(self.st.state.get("extra_pool") or 0) > 0
        else:
            round_["extra"] = extra_enabled and int(round_.get("answered", 0)) >= int(round_.get("target", 1))

    def _public(self, round_: dict) -> dict:
        question = Question(round_.get("question") or {})
        data = question.to_dict()
        for key in ("k", "answers", "correctIndices", "tip", "modelAnswer", "rubric"):
            data.pop(key, None)
        payload = {
            "id": round_["id"],
            "mode": round_.get("mode", "round"),
            "target": int(round_.get("target", 1)),
            "answered": int(round_.get("answered", 0)),
            "correct": int(round_.get("correct", 0)),
            "streak": int(round_.get("streak", 0)),
            "extra": bool(round_.get("extra", False)),
            "pending": bool(round_.get("pending", False)),
            "question": data,
            "extraPool": int(self.st.state.get("extra_pool") or 0),
            "status": self.status(),
        }
        return payload

    # ---------------------------------------------------------------- 作答

    def judge(self, question: Question, selections: list[int], text: str = "") -> bool:
        if question.type == "text":
            value = normalize_answer(text)
            if not value:
                return False
            return any(normalize_answer(item) == value for item in question.answers if item)
        expected = set(question.expected_indices())
        return expected == {int(i) for i in selections}

    def answer(self, selections: list[int] | None = None, text: str = "") -> dict:
        round_ = self.st.state.get("active_round")
        if not round_:
            raise EngineError("没有进行中的任务")

        question = Question(round_.get("question") or {})
        selections = [int(i) for i in (selections or [])]

        if question.type == "subjective":
            if not str(text or "").strip():
                raise EngineError("请先写下答案")
            round_["pending"] = True
            self.st.state["active_round"] = round_
            self.st.save_state()
            return {
                "pending_self": True,
                "modelAnswer": question.modelAnswer,
                "rubric": question.rubric,
                "tip": question.tip,
                "correctText": question.modelAnswer,
                "question": self._public(round_)["question"],
                "status": self.status(),
            }

        if question.type != "text" and not selections:
            raise EngineError("请先选择答案")

        correct = self.judge(question, selections, text)
        return self._settle(correct, quality=None, answered_text=text)

    def judge_self(self, correct: bool) -> dict:
        """主观题自评：家长 / AI 批改在桌面端的等价物。"""
        round_ = self.st.state.get("active_round")
        if not round_ or not round_.get("pending"):
            raise EngineError("没有待自评的题目")
        round_["pending"] = False
        return self._settle(bool(correct), quality=(4 if correct else 1), answered_text="")

    def _settle(self, correct: bool, quality: int | None, answered_text: str = "") -> dict:
        round_ = self.st.state["active_round"]
        question = Question(round_.get("question") or {})
        rules_snapshot = dict(round_.get("rules") or {})
        was_extra = bool(round_.get("extra"))
        mode = round_.get("mode", "round")
        target = int(round_.get("target", 1))

        state = self.st.state
        extra_pool = int(state.get("extra_pool") or 0)
        wrong = int(state.get("wrong_progress") or 0)

        # 累计加练：答错达阈值就增加待做题
        if not correct and bool(rules_snapshot.get("extraEnabled", True)):
            wrong += 1
            threshold = max(1, int(rules_snapshot.get("wrongThreshold", 3)))
            if wrong >= threshold:
                extra_pool += max(1, int(rules_snapshot.get("extraQuestions", 2)))
                wrong -= threshold
        # 答对加练题，待做数量减一
        if correct and was_extra and extra_pool > 0:
            extra_pool -= 1

        state["extra_pool"] = extra_pool
        state["wrong_progress"] = wrong

        # 连续答对玩法：答错（非加练）清零本段奖励
        if mode == "streak" and not correct and not was_extra:
            round_["earnedMs"] = 0

        if (not was_extra) or mode == "practice":
            round_["answered"] = int(round_.get("answered", 0)) + 1
            if correct:
                round_["correct"] = int(round_.get("correct", 0)) + 1
            round_["streak"] = int(round_.get("streak", 0)) + 1 if correct else 0
            if correct and bool(rules_snapshot.get("difficultyRewardEnabled", False)):
                rewards = rules_snapshot.get("difficultyRewards") or {}
                minutes = float(rewards.get(str(question.difficulty), 2))
                round_["earnedMs"] = int(round_.get("earnedMs", 0)) + int(minutes * 60000)

        self._record_progress(question.id, quality if quality is not None else (4 if correct else 1))

        # 答错就收进错题库；答对不动它（「全部收集」的取舍见 wrongbook.py）
        wrong_record = self._remember_wrong(question) if not correct else None

        streak_target = int(round_.get("streak", 0)) >= target
        answered_target = int(round_.get("answered", 0)) >= target
        base_done = streak_target if mode == "streak" else answered_target
        passed = True if mode == "streak" else int(round_.get("correct", 0)) >= math.ceil(
            target * float(rules_snapshot.get("passRatio", 0.6))
        )
        extra_enabled = bool(rules_snapshot.get("extraEnabled", True))
        finished = mode != "practice" and base_done and ((not passed) or (not extra_enabled) or extra_pool == 0)

        result: dict[str, Any] = {
            "correct": bool(correct),
            "correctIndices": question.expected_indices() if question.type != "text" else [],
            "answerText": question.answers[0] if (question.type == "text" and question.answers) else "",
            "correctText": question.correct_text(),
            "tip": question.tip,
            "finished": finished,
            "passed": bool(finished and passed),
            "wasExtra": was_extra,
            "answeredText": answered_text,
            # 错题库：这题是不是刚收进去、现在一共多少题
            "wrongAdded": bool(wrong_record and wrong_record.get("added")),
            "wrongTotal": int(wrong_record.get("total", 0)) if wrong_record else 0,
        }

        today = state["today"]
        if finished:
            grant = 0
            if passed:
                daily_reward = bool(rules_snapshot.get("difficultyRewardEnabled", False))
                requested = int(round_.get("earnedMs", 0)) if daily_reward else int(
                    rules_snapshot.get("sessionMinutes", 10)
                ) * 60000
                budget = self.rules().daily_ms() - int(today["used_ms"]) - int(today["credit_ms"])
                grant = max(0, min(requested, budget))
                today["credit_ms"] = int(today["credit_ms"]) + grant
                today["rounds_done"] = int(today["rounds_done"]) + 1
            state["active_round"] = None
            result["rewardMinutes"] = round(grant / 60000, 1)
            # 任务本轮统计
            result["roundAnswered"] = int(round_.get("answered", 0))
            result["roundCorrect"] = int(round_.get("correct", 0))
            result["roundTarget"] = target
            result["extraPool"] = extra_pool
        else:
            if mode == "streak" and not base_done:
                round_["extra"] = False
            self._next_question(round_, Rules.from_dict(rules_snapshot))
            if mode == "streak" and not base_done:
                round_["extra"] = False
            if mode == "practice":
                round_["extra"] = extra_pool > 0
            state["active_round"] = round_
            result["next"] = self._public(round_)

        # 统计
        counted = (not was_extra) or mode == "practice"
        self.st.history_bump(answered=1 if counted else 0, correct=1 if (counted and correct) else 0,
                             rounds=1 if (finished and passed) else 0)
        result["extraPoolAfter"] = extra_pool
        result["wrongProgress"] = wrong
        self.st.save_state()
        result["status"] = self.status()
        return result

    # ---------------------------------------------------------------- 错题库

    def _remember_wrong(self, question: Question) -> dict:
        """把一个错题收进错题库；第一次建本子时顺手加入出题范围。

        用户正开着错题库时必须写内存里那份：从磁盘重读再追加，会把他没保存的
        改动顶掉（错题库也是普通题库，可以被编辑）。
        """
        book = self.st.wrong_book
        active = None
        if self.bank and self.bank.path and Path(self.bank.path).name == WRONG_FILE:
            active = self.bank
        record = book.add(question, prefer=active)
        if record.get("added"):
            # 文件刚写完，缓存里的旧内容不能再用（同一时间刻度内 mtime 可能没变）
            self._bank_cache.pop(str(book.path), None)
            if record.get("created"):
                self.st.set_bank_selected(WRONG_FILE, True)
        return record

    # ---------------------------------------------------------------- 间隔重复

    def _record_progress(self, question_id: str, quality: int) -> None:
        progress = self.st.state.setdefault("progress", {})
        record = progress.get(question_id) or {"repetitions": 0, "interval_days": 0, "ease": 2.5, "due_at": 0}
        repetitions = int(record.get("repetitions", 0))
        interval = int(record.get("interval_days", 0))
        ease = float(record.get("ease", 2.5))
        quality = max(0, min(5, int(quality)))
        now = _now_ms()

        if quality < 3:
            repetitions = 0
            interval = 0
            due = now + 10 * 60 * 1000
        else:
            repetitions += 1
            if repetitions == 1:
                interval = 1
            elif repetitions == 2:
                interval = 6
            else:
                interval = int(round(interval * ease)) if interval else 6
                interval = max(1, min(36500, interval))
            due = now + interval * 86400000

        ease = max(1.3, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        progress[question_id] = {
            "repetitions": repetitions,
            "interval_days": interval,
            "ease": round(ease, 4),
            "due_at": due,
            "updated_at": now,
        }

    # ---------------------------------------------------------------- 兑换

    def redeem_options(self, tiers: list[int]) -> list[dict]:
        """给出各档位当前是否可兑换，供锁屏页渲染按钮。"""
        self.st.roll_day()
        rules = self.rules()
        today = self.st.state["today"]
        credit = int(today["credit_ms"])
        used = int(today["used_ms"])
        room = max(0, rules.daily_ms() - used)
        budget = min(credit, room)
        options = []
        for minutes in tiers:
            need = int(minutes) * 60000
            options.append(
                {
                    "minutes": int(minutes),
                    "enabled": need > 0 and budget >= need,
                    "short": 0 if budget >= need else int(math.ceil((need - budget) / 60000)),
                    "need": int(minutes),
                    "quota": room <= 0,
                }
            )
        return options

    def redeem(self, minutes: int) -> dict:
        """把答题余额兑换成自由使用的分钟数。

        预扣制：兑换当下就把额度计入 used_ms，中途提前结束也不退——否则
        「解锁 25 分钟、5 分钟后主动回锁、再解锁」可以反复刷时长。
        """
        self.st.roll_day()
        rules = self.rules()
        today = self.st.state["today"]
        need = int(minutes) * 60000
        if need <= 0:
            return {"ok": False, "reason": "invalid"}
        credit = int(today["credit_ms"])
        used = int(today["used_ms"])
        room = max(0, rules.daily_ms() - used)
        if room <= 0:
            return {"ok": False, "reason": "quota", "short": int(minutes), "creditAfter": credit}
        if credit < need or room < need:
            short = int(math.ceil((need - min(credit, room)) / 60000))
            return {"ok": False, "reason": "short", "short": short, "creditAfter": credit}

        today["credit_ms"] = credit - need
        today["used_ms"] = used + need
        self.st.history_bump(used_ms=need)
        self.st.save_state()
        return {"ok": True, "minutes": int(minutes), "creditAfter": today["credit_ms"]}

    # ---------------------------------------------------------------- 使用时长

    def consume(self, milliseconds: int) -> int:
        """消耗可用时长，返回实际消耗的毫秒数。"""
        self.st.roll_day()
        today = self.st.state["today"]
        rules = self.rules()
        credit = int(today["credit_ms"])
        used = int(today["used_ms"])
        room = max(0, rules.daily_ms() - used)
        amount = max(0, min(int(milliseconds), credit, room))
        if amount <= 0:
            return 0
        today["credit_ms"] = credit - amount
        today["used_ms"] = used + amount
        self.st.history_bump(used_ms=amount)
        self.st.save_state()
        return amount

    def abandon_round(self) -> None:
        """放弃当前任务（加练池保留）。"""
        self.st.state["active_round"] = None
        self.st.save_state()

    def reset_today(self) -> None:
        """家长重置当天额度（调试 / 特殊情况用）。"""
        today = self.st.state["today"]
        today["credit_ms"] = 0
        today["used_ms"] = 0
        today["rounds_done"] = 0
        self.st.state["active_round"] = None
        self.st.save_state()
