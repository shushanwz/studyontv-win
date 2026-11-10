"""界面冒烟测试：真实创建窗口、逐页渲染、模拟一次答题。

运行： python tests/ui_smoke.py [--shot 截图路径]
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="quizwin-ui-"))
(TMP / "banks").mkdir(parents=True, exist_ok=True)
for source in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(source, TMP / "banks" / source.name)
os.environ["QUIZWIN_DATA"] = str(TMP)

from run import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from quizwin.core.models import Question  # noqa: E402
from quizwin.ui.app import App  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("  [OK] " if condition else "  [FAIL] ") + name + ("" if condition else f"  {detail}"))
    if not condition:
        FAILURES.append(name)


def main() -> int:
    shot = None
    if "--shot" in sys.argv:
        shot = Path(sys.argv[sys.argv.index("--shot") + 1])

    app = App()
    app.update()
    print("窗口尺寸：", app.winfo_width(), "x", app.winfo_height())

    for key in ("bank", "rules", "about", "quiz"):
        try:
            app.set_page(key)
            app.update()
            check(f"页面渲染 {key}", True)
        except Exception as exc:  # pragma: no cover
            import traceback

            traceback.print_exc()
            check(f"页面渲染 {key}", False, str(exc))

    quiz = app.pages["quiz"]
    app.set_page("quiz")
    app.update()
    quiz.begin()
    app.update()
    check("进入答题视图", quiz.view in ("question", "self", "blocked"), quiz.view)

    if quiz.view == "question":
        payload = quiz.round["question"]
        item = app.engine.bank.find(payload["id"])
        check("题目存在于题库", item is not None)
        if item:
            if item.type in ("text", "subjective"):
                quiz.input_box.delete("1.0", "end")
                quiz.input_box.insert("1.0", item.answers[0] if item.answers else "答案")
                quiz.submit()
            else:
                quiz.choose(item.expected_indices()[0])
                if item.type == "multiple" and not quiz.answered:
                    # 多选题 choose() 只负责勾选，还得按一次确认；抽到多选题时
                    # 少了这一步就会误报「作答后出现反馈」失败（随机抽题的假阴性）
                    quiz.submit()
                app.update()
            if quiz.view == "self":
                check("主观题进入自评", True)
                quiz._self_judge(True)
                app.update()
            else:
                check("作答后出现反馈", quiz.answered and quiz.feedback is not None, str(quiz.view))
                if quiz.feedback:
                    check("反馈包含解析字段", "tip" in quiz.feedback)
                quiz.next_question()
                app.update()
                check("继续后进入下一题或结果页", quiz.view in ("question", "result", "self"), quiz.view)

    # 规则页交互：保存一次规则
    app.set_page("rules")
    app.update()
    rules_page = app.pages["rules"]
    rules_page.nums["questionsPerRound"].set("4")
    rules_page.save()
    app.update()
    check("规则保存生效", app.engine.rules().questionsPerRound == 4, str(app.engine.rules().questionsPerRound))

    # 题库页：新增一道题并保存
    app.set_page("bank")
    app.update()
    bank_page = app.pages["bank"]
    before = len(app.engine.bank.items)
    new_question = Question({"type": "single", "q": "这是一道界面测试题", "a": ["甲", "乙"], "k": 0})
    bank_page._on_saved(new_question, True)
    app.update()
    check("新增题目成功", len(app.engine.bank.items) == before + 1)
    check("题库文件已写盘", app.engine.bank.path.exists())

    # 题目编辑对话框：四种题型分别打开一次，确认不报错、能取到表单值
    from quizwin.ui.page_bank import QuestionDialog

    for kind in ("single", "multiple", "boolean", "subjective"):
        sample = Question({"type": kind, "q": "对话框里的示例题", "a": ["甲", "乙"], "k": 0})
        try:
            dialog = QuestionDialog(bank_page, app, sample, lambda *a: None)
            dialog.update()
            check(f"对话框打开（{kind}）", dialog.winfo_exists() == 1)
            dialog.destroy()
            app.update()
        except Exception as exc:
            import traceback

            traceback.print_exc()
            check(f"对话框打开（{kind}）", False, str(exc))

    # 编辑对话框保存：校验通过后写入题库
    try:
        dialog = QuestionDialog(bank_page, app, None, bank_page._on_saved)
        dialog.update()
        dialog.stem.insert("1.0", "对话框新增的一道题")
        for index, entry in enumerate(dialog.option_entries):
            entry.delete(0, "end")
            entry.insert(0, f"选项{index + 1}")
        dialog.save()
        app.update()
        check("对话框保存成功", len(app.engine.bank.items) == before + 2, str(len(app.engine.bank.items)))
    except Exception as exc:
        import traceback

        traceback.print_exc()
        check("对话框保存成功", False, str(exc))

    # 主题切换：两套主题来回切，页面重建后仍可渲染与答题
    for name in ("light", "dark"):
        try:
            app.apply_theme(name)
            app.update()
            check(f"主题切换 {name}", app.theme.name == name)
        except Exception as exc:
            import traceback

            traceback.print_exc()
            check(f"主题切换 {name}", False, str(exc))

    # 计时页与拦截页：只是渲染，不进入真实计时循环
    app.set_page("quiz")
    app.update()
    quiz = app.pages["quiz"]
    try:
        app.engine.st.state["today"]["credit_ms"] = 300000
        quiz.start_watch()
        app.update()
        check("计时页渲染", quiz.view == "watch")
        quiz.stop_watch()
        app.update()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        check("计时页渲染", False, str(exc))

    try:
        quiz.show_blocked("rounds", app.engine.status())
        app.update()
        check("拦截页渲染", quiz.view == "blocked")
        quiz.show_start()
        app.update()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        check("拦截页渲染", False, str(exc))

    if shot:
        app.update()
        app.after(200, lambda: _save_shot(app, shot))
        app.after(1200, app.destroy)
        app.mainloop()
    else:
        app.update()
        app.destroy()

    print("-" * 56)
    if FAILURES:
        print("失败：", ", ".join(FAILURES))
        return 1
    print("界面冒烟测试全部通过")
    return 0


def _save_shot(app, path: Path) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    from winshot import capture, window_handle

    path.parent.mkdir(parents=True, exist_ok=True)
    capture(window_handle(app), path)


if __name__ == "__main__":
    raise SystemExit(main())
