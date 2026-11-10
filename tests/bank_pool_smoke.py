"""题库管理冒烟测试：多库混合出题、删除、内置题库恢复、AI 输出容错。

纯逻辑，不启动界面。运行： python tests/bank_pool_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quizwin.core.engine import Engine  # noqa: E402
from quizwin.core.models import Bank, Question, loads_lenient  # noqa: E402
from quizwin.core.rules import Rules  # noqa: E402
from quizwin.core.storage import Storage  # noqa: E402
from quizwin.ui.bank_prompt import PROMPT, TOPIC_PRESETS, build_prompt  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def fresh(tag: str, seed: bool = False) -> Storage:
    data = Path(tempfile.mkdtemp(prefix=f"quizwin-bp-{tag}-")) / "data"
    (data / "banks").mkdir(parents=True)
    return Storage(data, seed=seed)


def write_bank(st: Storage, filename: str, name: str, questions: list[dict]) -> Path:
    path = st.banks_dir / filename
    payload = {"name": name, "version": 2, "items": questions}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def single(qid: str, stem: str, subject: str = "数学", level: str = "七年级") -> dict:
    return {
        "id": qid,
        "type": "single",
        "q": stem,
        "a": ["甲", "乙", "丙", "丁"],
        "k": 0,
        "difficulty": 2,
        "tip": "解析",
        "subject": subject,
        "level": level,
        "enabled": True,
    }


# ---------------------------------------------------------------- 1. AI 输出容错

def test_lenient() -> None:
    print("\n[1] 解析 AI 输出的各种包装")
    raw = '{"name": "x", "items": [{"q": "1+1=?", "a": ["2", "3"], "k": 0}]}'
    check("纯 JSON 能解析", loads_lenient(raw)["name"] == "x")

    fenced = '好的，下面是题库：\n```json\n' + raw + "\n```\n希望有用。"
    check("剥掉 ``` 围栏", loads_lenient(fenced)["name"] == "x")

    noisy = "这是结果\n" + raw + "\n以上共 1 题"
    check("截掉前后解释文字", loads_lenient(noisy)["name"] == "x")

    arr = '```\n[{"q": "a", "a": ["1", "2"], "k": 0}]\n```'
    check("裸数组也能解析", isinstance(loads_lenient(arr), list))

    try:
        loads_lenient("这不是 JSON")
        ok = False
    except ValueError as exc:
        ok = "JSON" in str(exc)
    check("坏内容给出可读错误", ok)

    try:
        loads_lenient("   ")
        ok2 = False
    except ValueError:
        ok2 = True
    check("空文件报错而不是静默", ok2)


# ---------------------------------------------------------------- 2. 多库出题

def test_mixed_pool() -> None:
    print("\n[2] 在选中的多个题库里随机出题")
    st = fresh("mix")
    path_a = write_bank(st, "a.json", "数学库", [single("qa1", "A 题 1"), single("qa2", "A 题 2")])
    path_b = write_bank(st, "b.json", "语文库", [single("qb1", "B 题 1", "语文"), single("qb2", "B 题 2", "语文")])

    st.set_active_bank("a.json")
    engine = Engine(st)
    check("默认只用当前题库", len(engine.pool()) == 2, str(len(engine.pool())))

    st.set_bank_selected("b.json", True)
    engine = Engine(st)
    check("勾选后两库混合", len(engine.pool()) == 4, str(len(engine.pool())))
    ids = {q.id for q in engine.pool()}
    check("两库题目都在池里", {"qa1", "qa2", "qb1", "qb2"} == ids, str(ids))
    check("quiz_scope 报出跨库", engine.quiz_scope()["mixed"] is True)

    # 只选 b：当前打开的 a 不参与
    st.select_only_bank("b.json")
    engine = Engine(st)
    pool = engine.pool()
    check("只选 b 时不含 a 的题", {q.id for q in pool} == {"qb1", "qb2"}, str({q.id for q in pool}))

    # 科目筛选仍然生效
    rules = Rules.from_dict({"quizSubjects": ["数学"]})
    check("科目筛选跨库生效", {q.id for q in engine.pool(rules)} == set(), "应为空")
    rules2 = Rules.from_dict({"quizSubjects": ["语文"]})
    check("科目筛选选语文得 2 题", len(engine.pool(rules2)) == 2)

    # 停用的题不进池
    st.select_all_banks()
    engine = Engine(st)
    bank_b = Bank.load(path_b)
    bank_b.items[0].enabled = False
    bank_b.save()
    # 显式推一下时间戳：连着两次保存可能落在同一时间刻度上，缓存不会失效
    stamp = time.time() + 2
    os.utime(path_b, (stamp, stamp))
    engine = Engine(st)
    check("停用题不参与抽题", len(engine.pool()) == 3, str(len(engine.pool())))

    # 抽题确实在池内循环，且不会连续重复
    st.select_all_banks()
    rules3 = Rules.from_dict({"questionsPerRound": 3, "playMode": "practice"})
    engine = Engine(st)
    payload = engine.start()
    first = payload["question"]["id"]
    engine.answer([0])
    second = engine.st.state["active_round"]["question"]["id"]
    check("连续两题不同", first != second, f"{first} vs {second}")
    check("新题来自合并池", second in {"qa1", "qa2", "qb1", "qb2"}, second)


# ---------------------------------------------------------------- 3. id 撞车

def test_duplicate_ids() -> None:
    print("\n[3] 两份题库带相同题目 id 时不串题")
    st = fresh("dup")
    write_bank(st, "one.json", "第一册", [single("same", "第一册的题")])
    write_bank(st, "two.json", "第二册", [single("same", "第二册的题")])
    st.select_all_banks()
    engine = Engine(st)
    pool = engine.pool()
    check("两题都保留", len(pool) == 2, str(len(pool)))
    ids = {q.id for q in pool}
    check("重复 id 被改名区分", len(ids) == 2, str(ids))
    check("改名带文件前缀", any(i.startswith("two#") for i in ids), str(ids))

    # 进度按 id 记录，不应该互相覆盖
    for question in pool:
        engine._record_progress(question.id, 4)
    progress = st.state["progress"]
    check("进度各存一条", len([k for k in progress if k in ids]) == 2, str(list(progress)))


# ---------------------------------------------------------------- 4. 删除题库

def test_delete() -> None:
    print("\n[4] 删除题库")
    st = fresh("del")
    write_bank(st, "a.json", "要删的", [single("a1", "题")])
    write_bank(st, "b.json", "留下的", [single("b1", "题")])
    st.set_active_bank("a.json")
    st.set_bank_selected("a.json", True)
    st.set_bank_selected("b.json", True)

    target = st.banks_dir / "a.json"
    trashed = st.delete_bank(target)

    check("源文件已移走", not target.exists())
    check("进了回收站", trashed.exists() and trashed.parent == st.trash_dir, str(trashed))
    check("回收站文件名带时间戳", len(trashed.stem) > len("a"), trashed.name)

    reloaded = Storage(st.data_dir, seed=False)
    check("出题范围里已移除", "a.json" not in reloaded.state["quiz_banks"], str(reloaded.state["quiz_banks"]))
    check("活跃题库自动切换", reloaded.state["active_bank"] == "b.json", reloaded.state["active_bank"])

    engine = Engine(reloaded)
    check("删完还能正常出题", len(engine.pool()) == 1)

    # 删光全部：engine.bank 允许为空
    reloaded.delete_bank(reloaded.banks_dir / "b.json")
    empty = Storage(st.data_dir, seed=False)
    check("没有题库时 active_bank 为空", empty.state["active_bank"] == "", empty.state["active_bank"])
    check("bank_infos 为空", empty.bank_infos() == [])
    check("active_bank_path 返回 None", empty.active_bank_path() is None)


# ---------------------------------------------------------------- 5. 内置题库

def test_builtin() -> None:
    print("\n[5] 内置题库自动集成 / 删除不复活 / 手动恢复")
    builtin = sorted((ROOT / "data" / "banks").glob("*.json"))
    check("项目里有 8 份内置题库", len(builtin) == 8, str(len(builtin)))

    st = fresh("builtin", seed=True)
    names = {info.filename for info in st.bank_infos()}
    check("首次启动自动铺入全部内置题库", names == {p.name for p in builtin}, str(sorted(names)))
    check("题数不为零", all(info.count > 0 for info in st.bank_infos()))

    victim = builtin[0].name
    st.delete_bank(st.banks_dir / victim)
    again = Storage(st.data_dir, seed=True)
    after = {info.filename for info in again.bank_infos()}
    check("删掉的内置题库不会自己复活", victim not in after, str(sorted(after)))
    check("其余内置题库仍在", len(after) == len(builtin) - 1, str(len(after)))
    check("删过的名字记在状态里", victim in again.state["banks_removed"], str(again.state["banks_removed"]))

    created = again.restore_builtin()
    restored = {info.filename for info in again.bank_infos()}
    check("手动恢复把它找回来", victim in restored and victim in created, str(created))
    check("恢复后清空删除记录", again.state["banks_removed"] == [])
    check("恢复不会重复铺一遍", len(restored) == len(builtin), str(len(restored)))

    # 用户改过的同名题库不被覆盖
    target = again.banks_dir / victim
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["name"] = "我自己改过的"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    Storage(again.data_dir, seed=True)
    kept = json.loads(target.read_text(encoding="utf-8"))["name"]
    check("不覆盖用户改过的同名题库", kept == "我自己改过的", kept)


# ---------------------------------------------------------------- 6. 提示词

def test_prompt() -> None:
    print("\n[6] 自建题库的 AI 提示词")
    for word in ("小学", "初中", "高中", "语文", "数学", "英语", "物理", "化学", "生物",
                 "历史", "地理", "政治", "常识", "电脑", "人工智能", "哲学", "古文"):
        check(f"覆盖「{word}」", word in PROMPT, word)

    for field in ('"type"', '"q"', '"a"', '"k"', '"correctIndices"', '"answers"',
                  '"difficulty"', '"tip"', '"subject"', '"level"'):
        check(f"写明字段 {field}", field in PROMPT)

    check("要求禁用争议题", "争议" in PROMPT)
    check("要求分批输出", "分批" in PROMPT)
    check("要求输出前自检", "自检" in PROMPT)
    check("主题包齐全", len(TOPIC_PRESETS) >= 6, str(list(TOPIC_PRESETS)))
    check("不带主题时不追加", build_prompt() == PROMPT)
    added = build_prompt(["电脑与 AI", "古文段落"])
    check("加主题后追加重点", "【本次重点】" in added and "人工智能" in added)
    check("未知主题被忽略", build_prompt(["不存在的主题"]) == PROMPT)


def main() -> int:
    test_lenient()
    test_mixed_pool()
    test_duplicate_ids()
    test_delete()
    test_builtin()
    test_prompt()

    print(f"\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for item in FAILED:
            print("  !", item)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
