"""错题库冒烟测试：自动收集、去重、自动进入出题范围、清空、重建。

纯逻辑，不启动界面。运行： python tests/wrongbook_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quizwin.core.engine import Engine  # noqa: E402
from quizwin.core.models import Question  # noqa: E402
from quizwin.core.storage import Storage  # noqa: E402
from quizwin.core.wrongbook import WRONG_FILE, WRONG_NAME, fingerprint  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def fresh(tag: str) -> Storage:
    data = Path(tempfile.mkdtemp(prefix=f"quizwin-wb-{tag}-")) / "data"
    (data / "banks").mkdir(parents=True)
    return Storage(data, seed=False)


def write_bank(st: Storage, filename: str, name: str, questions: list[dict]) -> Path:
    path = st.banks_dir / filename
    payload = {"name": name, "version": 2, "items": questions}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def single(qid: str, stem: str, k: int = 0, subject: str = "数学") -> dict:
    return {
        "id": qid,
        "type": "single",
        "q": stem,
        "a": ["甲", "乙", "丙", "丁"],
        "k": k,
        "difficulty": 2,
        "tip": f"{stem}的解析",
        "subject": subject,
        "level": "七年级",
        "enabled": True,
    }


def subjective(qid: str, stem: str) -> dict:
    return {
        "id": qid,
        "type": "subjective",
        "q": stem,
        "difficulty": 3,
        "modelAnswer": "参考答案",
        "rubric": "写到要点即可",
        "subject": "语文",
        "level": "七年级",
    }


def practice(st: Storage, filename: str = "base.json") -> None:
    st.set_active_bank(filename)
    st.state["rules"] = {"playMode": "practice"}
    st.save_state()


def answer_wrong(engine: Engine) -> dict:
    """开一题、故意答错，返回结算结果（附上被答错的那道题，便于后续断言）。"""
    payload = engine.start()
    question = payload["question"]
    options = question.get("a") or []
    correct = set(question.get("correctIndices") or [])
    if question.get("type") in ("single", "boolean"):
        correct = {int(question.get("k", 0))}
    wrong = next(index for index in range(len(options)) if index not in correct)
    result = engine.answer([wrong])
    result["_question"] = question
    return result


wrong_path = lambda st: st.banks_dir / WRONG_FILE  # noqa: E731


# ---------------------------------------------------------------- 1. 收集

def test_collect() -> None:
    print("\n[1] 答错自动收进错题库")
    st = fresh("collect")
    write_bank(st, "base.json", "基础", [single("s1", "1+1=?"), single("s2", "2+2=?"), single("s3", "3+3=?")])
    practice(st)
    engine = Engine(st)

    check("一开始没有错题库", not wrong_path(st).exists())
    result = answer_wrong(engine)
    check("答错被判定为错", result["correct"] is False)
    check("错题库文件已生成", wrong_path(st).exists())
    check("反馈报出「已收进」", result["wrongAdded"] is True, str(result.get("wrongAdded")))
    check("反馈报出总数 1", result["wrongTotal"] == 1, str(result.get("wrongTotal")))
    check("错题库自动加入出题范围", WRONG_FILE in st.selected_banks(), str(st.selected_banks()))
    check("题库列表里能看到它", WRONG_FILE in {info.filename for info in st.bank_infos()})
    check("名字叫「错题库」", st.wrong_book.bank().name == WRONG_NAME, st.wrong_book.bank().name)
    check("不算内置题库", not st.is_builtin(wrong_path(st)))

    # 同一道题两次答错，只留一份
    question = Question(result["_question"])
    before = st.wrong_book.count()
    again = st.wrong_book.add(question)
    check("同题不重复收", again["added"] is False, str(again))
    check("总数不变", st.wrong_book.count() == before, str(st.wrong_book.count()))

    # 池子里不能出现同一道题的两份（源题库 + 错题库副本）
    pool = engine.pool()
    check("出题池按内容去重", len(pool) == 3, str([q.q for q in pool]))
    texts = [q.q for q in pool]
    check("池里没有重复题干", len(texts) == len(set(texts)), str(texts))

    # 副本保留原题的全部信息
    copy = next(item for item in st.wrong_book.bank().items if item.q == question.q)
    check("副本保留选项", copy.a == ["甲", "乙", "丙", "丁"], str(copy.a))
    check("副本保留答案", copy.k == int(question.k), f"{copy.k} / {question.k}")
    check("副本保留解析", copy.tip == "解析" or copy.tip.endswith("的解析"), copy.tip)
    check("副本保留科目年级", (copy.subject, copy.level) == ("数学", "七年级"), f"{copy.subject}/{copy.level}")


# ---------------------------------------------------------------- 2. 答对不动它

def test_keep_on_correct() -> None:
    print("\n[2] 答对不会把错题删掉")
    st = fresh("keep")
    write_bank(st, "base.json", "基础", [single("s1", "1+1=?"), single("s2", "2+2=?")])
    practice(st)
    engine = Engine(st)
    answer_wrong(engine)
    total = st.wrong_book.count()
    check("先攒了 1 题", total == 1, str(total))

    # 来一道答对的
    payload = engine.start()
    question = payload["question"]
    right = int(question.get("k", 0))
    engine.answer([right])
    check("答对后错题库数量不变", st.wrong_book.count() == total, str(st.wrong_book.count()))


# ---------------------------------------------------------------- 3. 清空

def test_clear() -> None:
    print("\n[3] 清空错题库")
    st = fresh("clear")
    write_bank(st, "base.json", "基础", [single("s1", "1+1=?"), single("s2", "2+2=?")])
    practice(st)
    engine = Engine(st)
    answer_wrong(engine)
    answer_wrong(engine)
    check("先攒了两题", st.wrong_book.count() == 2, str(st.wrong_book.count()))

    removed = st.wrong_book.clear()
    check("清空返回清掉的题数", removed == 2, str(removed))
    check("文件还在（题库页那一行不会消失）", wrong_path(st).exists())
    check("计数归零", st.wrong_book.count() == 0)
    check("出题范围没被清空", WRONG_FILE in st.selected_banks(), str(st.selected_banks()))

    # 再答错还会长回来
    answer_wrong(engine)
    check("清空后还能继续收集", st.wrong_book.count() == 1, str(st.wrong_book.count()))


# ---------------------------------------------------------------- 4. 删了重建

def test_delete_then_recreate() -> None:
    print("\n[4] 删掉错题库后，下次答错会重建")
    st = fresh("del")
    write_bank(st, "base.json", "基础", [single("s1", "1+1=?"), single("s2", "2+2=?")])
    practice(st)
    engine = Engine(st)
    answer_wrong(engine)
    check("先有错题库", wrong_path(st).exists())

    st.delete_bank(wrong_path(st))
    check("删除后文件不在了", not wrong_path(st).exists())
    check("缓存也失效了", st.wrong_book.count() == 0)

    engine = Engine(st)
    result = answer_wrong(engine)
    check("答错又重建了", wrong_path(st).exists())
    check("重建后重新加入出题范围", WRONG_FILE in st.selected_banks(), str(st.selected_banks()))
    check("重建的那次报「新增」", result["wrongAdded"] is True)


# ---------------------------------------------------------------- 5. 用户关掉开关

def test_opt_out() -> None:
    print("\n[5] 用户把开关关掉后，不被程序强行打开")
    st = fresh("optout")
    write_bank(st, "base.json", "基础", [single("s1", "1+1=?"), single("s2", "2+2=?")])
    practice(st)
    engine = Engine(st)
    answer_wrong(engine)
    check("先自动加入了", WRONG_FILE in st.selected_banks())

    st.set_bank_selected(WRONG_FILE, False)
    check("关掉后不在范围里", WRONG_FILE not in st.selected_banks(), str(st.selected_banks()))

    engine = Engine(st)
    answer_wrong(engine)
    check("再答错也不强行打开", WRONG_FILE not in st.selected_banks(), str(st.selected_banks()))
    check("但照样收进去了", st.wrong_book.count() >= 1, str(st.wrong_book.count()))


# ---------------------------------------------------------------- 6. 主观题

def test_subjective() -> None:
    print("\n[6] 主观题自评「没答对」也收")
    st = fresh("subject")
    write_bank(st, "base.json", "主观", [subjective("z1", "说说你的看法")])
    practice(st)
    engine = Engine(st)
    payload = engine.start()
    check("出的是主观题", payload["question"]["type"] == "subjective", str(payload["question"].get("type")))
    engine.answer([], "我觉得……")
    result = engine.judge_self(False)
    check("自评不对后收进错题库", st.wrong_book.count() == 1, str(st.wrong_book.count()))
    stored = st.wrong_book.bank().items[0]
    check("参考答案一起存下来", stored.modelAnswer == "参考答案", stored.modelAnswer)
    check("评分要点一起存下来", stored.rubric == "写到要点即可", stored.rubric)
    check("反馈里也说了", result.get("wrongAdded") is True)


# ---------------------------------------------------------------- 7. 编辑中收录

def test_editing() -> None:
    print("\n[7] 正开着错题库编辑时收录，不会顶掉未保存的改动")
    st = fresh("edit")
    write_bank(st, "base.json", "基础", [single("s1", "1+1=?"), single("s2", "2+2=?")])
    practice(st)
    engine = Engine(st)
    st.wrong_book.add(Question(single("s1", "1+1=?")))

    engine.load_bank(wrong_path(st))
    engine.bank.name = "我改的名字"
    engine.bank.dirty = True

    record = engine._remember_wrong(Question(single("s2", "2+2=?")))
    check("收录成功", record["added"] is True, str(record))
    check("内存里那份没被替换", engine.bank.name == "我改的名字", engine.bank.name)
    check("内存里能看到新题", len(engine.bank.items) == 2, str(len(engine.bank.items)))
    payload = json.loads(wrong_path(st).read_text(encoding="utf-8"))
    check("文件里也写进去了", len(payload["items"]) == 2, str(len(payload["items"])))
    check("改过的名字一并落盘", payload["name"] == "我改的名字", payload["name"])


# ---------------------------------------------------------------- 8. 指纹

def test_fingerprint() -> None:
    print("\n[8] 内容指纹")
    a = Question(single("x1", "1+1=?"))
    b = Question(single("x2", "1+1=?"))
    check("换 id 不影响指纹", fingerprint(a) == fingerprint(b))
    c = Question(single("x1", "1+1=? "))
    check("首尾空白不影响指纹", fingerprint(a) == fingerprint(c))
    d = Question(single("x1", "1+2=?", k=1))
    check("改了答案就不是同一题", fingerprint(a) != fingerprint(d))
    e = Question(single("x1", "1+1=?1"))
    check("改了题干就不是同一题", fingerprint(a) != fingerprint(e))


def main() -> int:
    test_collect()
    test_keep_on_correct()
    test_clear()
    test_delete_then_recreate()
    test_opt_out()
    test_subjective()
    test_editing()
    test_fingerprint()

    print(f"\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for item in FAILED:
            print("  !", item)
        return 1
    print("错题库冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
