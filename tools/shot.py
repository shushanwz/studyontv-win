"""截屏工具（开发自用）：启动程序、切到指定页面、截图后退出。

用法： python tools/shot.py quiz shots/quiz.png [--answer]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="quizwin-shot-"))
(TMP / "banks").mkdir(parents=True, exist_ok=True)
for source in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(source, TMP / "banks" / source.name)
os.environ["QUIZWIN_DATA"] = str(TMP)

from run import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from quizwin.ui.app import App  # noqa: E402


def grab(app, path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from winshot import capture, window_handle

    capture(window_handle(app), path)


def main() -> int:
    page = sys.argv[1] if len(sys.argv) > 1 else "quiz"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "shots" / f"{page}.png"
    answer = "--answer" in sys.argv

    app = App()
    app.update()
    if "--light" in sys.argv:
        app.apply_theme("light")
        app.update()
    if "--bank" in sys.argv:
        target_bank = sys.argv[sys.argv.index("--bank") + 1]
        app.engine.load_bank(TMP / "banks" / target_bank)
    if "--wrongbook" in sys.argv:
        # 造几条错题再切过去，用来截「答错自动收集」那一屏
        from quizwin.core.wrongbook import WRONG_FILE

        for item in app.engine.bank.items[:5]:
            app.storage.wrong_book.add(item)
        app.storage.set_bank_selected(WRONG_FILE, True)
        app.engine.load_bank(TMP / "banks" / WRONG_FILE)
    app.set_page(page)
    app.update()
    if "--wrongbook" in sys.argv:
        # 错题库排在列表末尾，滚到底才看得见
        app.pages["bank"].list_frame.canvas.yview_moveto(1.0)
        app.update()

    if page == "quiz":
        quiz = app.pages["quiz"]
        if "--type" in sys.argv:
            wanted = sys.argv[sys.argv.index("--type") + 1]
            quiz.reload()
            app.update()
            item = next((q for q in app.engine.bank.items if q.type == wanted), None)
            if item and app.engine.st.state.get("active_round"):
                app.engine.st.state["active_round"]["question"] = item.to_dict(for_export=False)
                app.engine.st.save_state()
                quiz.reload()
                app.update()
        if "--start" in sys.argv:
            quiz.show_start()
        elif "--blocked" in sys.argv:
            rules = app.engine.rules()
            app.engine.st.state["today"]["rounds_done"] = rules.roundsPerDay
            app.engine.st.state["today"]["credit_ms"] = 0
            app.engine.st.save_state()
            quiz.reload()
        else:
            quiz.begin()
        app.update()
        if "--watch" in sys.argv:
            app.engine.st.state["today"]["credit_ms"] = 600000
            app.engine.st.save_state()
            quiz.start_watch()
        app.update()
        if answer and quiz.view == "question":
            item = app.engine.bank.find(quiz.round["question"]["id"])
            if item:
                if item.type in ("text", "subjective"):
                    quiz.input_box.focus_set()
                    quiz.input_box.event_generate("<FocusIn>")
                    quiz.input_box.delete("1.0", "end")
                    value = item.answers[0] if item.answers else (item.modelAnswer or "测试作答")
                    quiz.input_box.insert("1.0", value)
                    quiz.submit()
                else:
                    quiz.choose(item.expected_indices()[0] if item.expected_indices() else 0)
                app.update()
        if "--result" in sys.argv:
            # 让结算页拿到一笔真实解锁额度，才能显示出「开始使用」
            app.engine.st.state["today"]["credit_ms"] = 600000
            app.engine.st.state["today"]["rounds_done"] = 1
            app.engine.st.save_state()
            quiz.feedback = {
                "passed": True,
                "finished": True,
                "correct": True,
                "rewardMinutes": 10,
                "roundAnswered": 5,
                "roundCorrect": 5,
                "roundTarget": 5,
                "extraPoolAfter": 0,
            }
            quiz.view = "result"
            quiz.render()
            app.update()
    dialog = None
    if page == "bank" and "--dialog" in sys.argv:
        bank_page = app.pages["bank"]
        from quizwin.core.models import Question

        from quizwin.ui.page_bank import QuestionDialog

        dialog = QuestionDialog(
            bank_page,
            app,
            Question({"type": "single", "q": "示例题目", "a": ["甲", "乙"], "k": 0}),
            lambda *a: None,
        )
        app.update()

    app.update_idletasks()
    app.update()
    app.attributes("-topmost", True)
    app.lift()
    app.focus_force()
    app.update()
    def finish():
        app.lift()
        app.update()
        target = dialog if dialog is not None and dialog.winfo_exists() else app
        target.lift()
        target.update()
        grab(target, out)
        print("已截图：", out)
        app.destroy()

    app.after(1500, finish)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
