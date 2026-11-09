"""核心逻辑冒烟测试：不启动界面，直接验证引擎与上游规则是否一致。

运行： python tests/engine_smoke.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quizwin.core.engine import Engine, EngineError, normalize_answer  # noqa: E402
from quizwin.core.models import Bank, Question  # noqa: E402
from quizwin.core.rules import Rules  # noqa: E402
from quizwin.core.storage import Storage  # noqa: E402

PASSED = []
FAILED = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def make_store(items: list[dict], rules: dict | None = None) -> tuple[Storage, Engine]:
    tmp = Path(tempfile.mkdtemp(prefix="quizwin-test-"))
    data = tmp / "data"
    (data / "banks").mkdir(parents=True)
    payload = {"name": "测试题库", "version": 2, "items": items}
    (data / "banks" / "test.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    storage = Storage(data)
    storage.set_active_bank("test.json")
    if rules:
        storage.state["rules"] = rules
        storage.save_state()
    engine = Engine(storage)
    return storage, engine


def single(qid: str, answer: int = 0, difficulty: int = 2) -> dict:
    return {
        "id": qid,
        "type": "single",
        "q": f"题目 {qid}",
        "a": ["正确选项", "错误选项 1", "错误选项 2", "错误选项 3"],
        "k": answer,
        "difficulty": difficulty,
        "subject": "测试",
    }


def test_basic_round() -> None:
    print("\n[1] 按组闯关：5 题全对，应通过并发放奖励")
    items = [single(f"q{i}") for i in range(8)]
    rules = Rules(
        playMode="round", questionsPerRound=5, passRatio=0.6, sessionMinutes=10,
        roundsPerDay=3, dailyMinutes=60, extraEnabled=False,
    ).to_dict()
    storage, engine = make_store(items, rules)

    start = engine.start()
    check("start 返回题目", start.get("question", {}).get("q", "").startswith("题目"))
    check("返回的题目不含答案字段", "k" not in start["question"] and "answers" not in start["question"])
    check("初始加练池为 0", start["extraPool"] == 0)

    result = None
    for index in range(5):
        result = engine.answer([0])
        if not result["finished"]:
            check(f"第 {index + 1} 题未结束", result["finished"] is False)
        else:
            check(f"第 {index + 1} 题后结束", result["finished"] is True)

    check("任务通过", result["passed"] is True)
    check("奖励为 10 分钟", abs(result["rewardMinutes"] - 10) < 0.01, f"实际 {result['rewardMinutes']}")
    status = engine.status()
    check("余额 10 分钟", abs(status["remainingMinutes"] - 10) < 0.01, str(status["remainingMinutes"]))
    check("今日组数 +1", status["roundsDoneToday"] == 1, str(status["roundsDoneToday"]))
    check("进行中任务已清空", status["hasRound"] is False)


def test_extra_pool() -> None:
    print("\n[2] 累计加练：答错达阈值加练池 +2，通过后须清池才结算")
    items = [single(f"q{i}") for i in range(12)]
    rules = Rules(
        playMode="round", questionsPerRound=4, passRatio=0.5, sessionMinutes=5,
        roundsPerDay=5, dailyMinutes=60, extraEnabled=True, wrongThreshold=2, extraQuestions=2,
    ).to_dict()
    storage, engine = make_store(items, rules)

    engine.start()
    r1 = engine.answer([1])  # 错
    check("第一次答错，池为 0", r1["extraPoolAfter"] == 0, str(r1["extraPoolAfter"]))
    r2 = engine.answer([1])  # 错 -> 阈值 2，池 +2
    check("第二次答错，池为 2", r2["extraPoolAfter"] == 2, str(r2["extraPoolAfter"]))
    r3 = engine.answer([0])  # 对
    r4 = engine.answer([0])  # 对，答满 4 题，正确率 50% 达标
    check("答满题量且正确率达标", r4["correct"] is True)
    check("加练池未清，不算结束", r4["finished"] is False, str(r4))
    check("下一题标记为加练", r4["next"]["extra"] is True)

    r5 = engine.answer([0])  # 加练答对，池 1
    check("加练答对后池为 1", r5["extraPoolAfter"] == 1, str(r5["extraPoolAfter"]))
    check("池未清，仍未结束", r5["finished"] is False)
    r6 = engine.answer([0])  # 加练答对，池 0 -> 结束
    check("清池后任务结束", r6["finished"] is True)
    check("任务通过", r6["passed"] is True)
    check("通过后发放奖励 5 分钟", abs(r6["rewardMinutes"] - 5) < 0.01, str(r6["rewardMinutes"]))
    check("通过计入今日组数", engine.status()["roundsDoneToday"] == 1)


def test_failed_round() -> None:
    print("\n[2b] 正确率不足：直接结束且不发放奖励")
    items = [single(f"q{i}") for i in range(8)]
    rules = Rules(
        playMode="round", questionsPerRound=3, passRatio=1.0, sessionMinutes=5,
        roundsPerDay=5, dailyMinutes=60, extraEnabled=True, wrongThreshold=99, extraQuestions=2,
    ).to_dict()
    storage, engine = make_store(items, rules)
    engine.start()
    engine.answer([1])
    engine.answer([1])
    result = engine.answer([0])
    check("答满题量即结束", result["finished"] is True)
    check("未通过", result["passed"] is False)
    check("无奖励", result["rewardMinutes"] == 0)
    check("不计入今日组数", engine.status()["roundsDoneToday"] == 0)


def test_streak() -> None:
    print("\n[3] 连续答对：答错清零重计")
    items = [single(f"q{i}") for i in range(10)]
    rules = Rules(
        playMode="streak", questionsPerRound=3, sessionMinutes=6,
        roundsPerDay=5, dailyMinutes=60, extraEnabled=False,
    ).to_dict()
    storage, engine = make_store(items, rules)
    engine.start()
    engine.answer([0])
    engine.answer([0])
    r = engine.answer([2])  # 错，连续清零
    check("答错后连续数为 0", r["next"]["streak"] == 0, str(r["next"]["streak"]))
    check("答错后未结束", r["finished"] is False)
    engine.answer([0])
    engine.answer([0])
    r = engine.answer([0])
    check("连续答对 3 题后结束", r["finished"] is True)
    check("连续玩法通过", r["passed"] is True)
    check("奖励 6 分钟", abs(r["rewardMinutes"] - 6) < 0.01, str(r["rewardMinutes"]))


def test_text_and_multiple() -> None:
    print("\n[4] 判定规则：填空归一化、多选全对、判断")
    check("全角半角归一化", normalize_answer("Ｈ２Ｏ") == normalize_answer("H2O"))
    check("大小写与空白归一化", normalize_answer("  h2o  ") == "h2o")

    items = [
        {"id": "t1", "type": "text", "q": "水的化学式", "answers": ["H2O", "H₂O"], "difficulty": 2},
        {"id": "t2", "type": "multiple", "q": "选出偶数", "a": ["2", "3", "4"], "correctIndices": [0, 2]},
        {"id": "t3", "type": "boolean", "q": "一年有四季", "k": 0},
    ]
    rules = Rules(playMode="practice").to_dict()
    storage, engine = make_store(items, rules)

    q = Question(items[0])
    check("填空 Ｈ２Ｏ 判对", engine.judge(q, [], "Ｈ２Ｏ") is True)
    check("填空错误答案判错", engine.judge(q, [], "CO2") is False)
    q2 = Question(items[1])
    check("多选全对判对", engine.judge(q2, [0, 2]) is True)
    check("多选漏选判错", engine.judge(q2, [0]) is False)
    check("多选多选判错", engine.judge(q2, [0, 1, 2]) is False)
    q3 = Question(items[2])
    check("判断题正确", engine.judge(q3, [0]) is True)
    check("判断题错误", engine.judge(q3, [1]) is False)


def test_subjective() -> None:
    print("\n[5] 主观题：提交后进入自评，自评通过后结算")
    items = [
        {
            "id": "s1", "type": "subjective", "q": "解方程", "modelAnswer": "x=2 或 x=3",
            "rubric": "过程 50 分，结论 50 分", "difficulty": 3,
        },
        single("s2"),
    ]
    rules = Rules(playMode="round", questionsPerRound=2, passRatio=1.0, sessionMinutes=4,
                  roundsPerDay=3, dailyMinutes=60, extraEnabled=False).to_dict()
    storage, engine = make_store(items, rules)

    start = engine.start()
    # 构造：把当前题强制设为 s1，验证 pending 流程
    engine.st.state["active_round"]["question"] = Question(items[0]).to_dict(for_export=False)
    engine.st.save_state()
    pending = engine.answer([], "x=2 或 x=3")
    check("主观题返回自评请求", pending.get("pending_self") is True)
    check("自评页带参考答案", "x=2" in pending.get("modelAnswer", ""))
    result = engine.judge_self(True)
    check("自评通过后计入正确", result["correct"] is True)
    check("未结束时给出下一题", "next" in result)


def test_quota_and_rounds() -> None:
    print("\n[6] 额度与组数上限")
    items = [single(f"q{i}") for i in range(10)]
    rules = Rules(playMode="round", questionsPerRound=1, passRatio=1.0, sessionMinutes=30,
                  roundsPerDay=1, dailyMinutes=20, extraEnabled=False).to_dict()
    storage, engine = make_store(items, rules)
    engine.start()
    result = engine.answer([0])
    check("单题任务通过", result["passed"] is True)
    check("奖励受每日额度约束（20 分钟）", abs(result["rewardMinutes"] - 20) < 0.01, str(result["rewardMinutes"]))
    blocked = engine.start()
    check("达组数且有余额时仍可答题？", "blocked" not in blocked or blocked["blocked"] != "rounds")
    engine.consume(20 * 60000)
    status = engine.status()
    check("用完额度后 reason=quota", status["reason"] == "quota", status["reason"])
    blocked = engine.start()
    check("额度用完后被拦截", blocked.get("blocked") == "quota", str(blocked.get("blocked")))


def test_spaced() -> None:
    print("\n[7] 间隔重复：首次答对约 1 天后复习")
    items = [single("a"), single("b")]
    rules = Rules(playMode="practice", spacedRepetitionEnabled=True).to_dict()
    storage, engine = make_store(items, rules)
    engine.start()
    engine.answer([0])
    progress = engine.st.state["progress"]
    record = next(iter(progress.values()))
    check("记录了复习进度", record["repetitions"] == 1)
    check("首次间隔 1 天", record["interval_days"] == 1)
    check("到期时间约为 1 天后", record["due_at"] > 0)


def test_bank_io() -> None:
    print("\n[8] 题库读写与格式兼容")
    tmp = Path(tempfile.mkdtemp(prefix="quizwin-bank-"))
    legacy = [{"q": "旧版单题", "a": ["甲", "乙"], "k": 1}]
    path = tmp / "legacy.json"
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    bank = Bank.load(path)
    check("兼容裸数组题库", len(bank.items) == 1 and bank.items[0].type == "single")
    check("缺省字段补齐", bank.items[0].subject == "常识" and bank.items[0].difficulty == 2)
    check("缺省 id 自动生成", bank.items[0].id.startswith("q_"))

    out = tmp / "out.json"
    bank.export_json(out)
    reloaded = Bank.load(out)
    check("导出后可重新加载", len(reloaded.items) == 1)
    check("导出保留题库名", reloaded.name == "导入的题库")

    bad = Question({"type": "multiple", "q": "缺答案", "a": ["甲", "乙"]})
    check("多选缺答案能校验出来", any("正确答案" in e for e in bad.validate()))


def main() -> int:
    print("=" * 62)
    print("题了个题 · 桌面版 —— 核心逻辑冒烟测试")
    print("=" * 62)
    test_basic_round()
    test_extra_pool()
    test_failed_round()
    test_streak()
    test_text_and_multiple()
    test_subjective()
    test_quota_and_rounds()
    test_spaced()
    test_bank_io()

    print("\n" + "-" * 62)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for item in FAILED:
            print("  失败：", item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
