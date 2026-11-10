"""题库页界面冒烟测试：删除题库、勾选出题范围、自建题库对话框。

运行： python tests/bank_ui_smoke.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="quizwin-bankui-"))
(TMP / "banks").mkdir(parents=True, exist_ok=True)
for source in (ROOT / "data" / "banks").glob("*.json"):
    shutil.copy(source, TMP / "banks" / source.name)
os.environ["QUIZWIN_DATA"] = str(TMP)
os.environ["QUIZWIN_NO_GUARD"] = "1"

from run import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from quizwin.ui.app import App  # noqa: E402
from quizwin.ui.bank_prompt import BankPromptDialog  # noqa: E402
from quizwin.ui.page_bank import BankRow  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("  [OK] " if condition else "  [FAIL] ") + name + ("" if condition else f"  {detail}"))
    if not condition:
        FAILURES.append(name)


def rows(page) -> list[BankRow]:
    return [w for w in page.rows_holder.winfo_children() if isinstance(w, BankRow)]


def main() -> int:
    app = App()
    app.update()
    app.set_page("bank")
    app.update()
    page = app.pages["bank"]
    storage = app.storage

    print("\n[1] 题库列表")
    check("八份内置题库都列出来", len(rows(page)) == 8, str(len(rows(page))))
    check("统计行显示 1/8", "1/8" in page.scope_label.cget("text"), page.scope_label.cget("text"))
    check("默认只有当前题库参与", len(page.selected_names()) == 1, str(page.selected_names()))

    print("\n[2] 勾选参与出题的题库")
    infos = storage.bank_infos()
    target = next(info for info in infos if info.filename not in page.selected_names())
    page.toggle_bank_selected(target, True)
    app.update()
    check("状态里记下两份", len(storage.state["quiz_banks"]) == 2, str(storage.state["quiz_banks"]))
    check("统计行变成 2/8", "2/8" in page.scope_label.cget("text"), page.scope_label.cget("text"))
    check("可抽题数翻倍", "200 题" in page.scope_label.cget("text"), page.scope_label.cget("text"))
    check("池子确实是两百题", len(app.engine.pool()) == 200, str(len(app.engine.pool())))

    page.toggle_bank_selected(target, False)
    app.update()
    check("取消后回到 1/8", "1/8" in page.scope_label.cget("text"), page.scope_label.cget("text"))

    only = next(iter(page.selected_names()))
    guarded = next(info for info in infos if info.filename == only)
    page.toggle_bank_selected(guarded, False)
    app.update()
    check("最后一份关不掉", len(page.selected_names()) == 1, str(page.selected_names()))

    page.select_all_banks()
    app.update()
    check("全选后 8/8", "8/8" in page.scope_label.cget("text"), page.scope_label.cget("text"))
    check("全选池为 800 题", len(app.engine.pool()) == 800, str(len(app.engine.pool())))

    print("\n[3] 删除题库")
    victim = storage.bank_infos()[0]
    before = len(storage.bank_infos())
    with mock.patch("quizwin.ui.page_bank.messagebox.askyesno", return_value=True):
        page.delete_bank(victim)
    app.update()
    check("列表少一份", len(rows(page)) == before - 1, str(len(rows(page))))
    check("文件进了回收站", len(list(storage.trash_dir.glob("*.json"))) == 1)
    check("出题范围同步剔除", victim.filename not in storage.state["quiz_banks"])
    check("界面照样能抽题", len(app.engine.pool()) > 0)

    with mock.patch("quizwin.ui.page_bank.messagebox.askyesno", return_value=False):
        page.delete_bank(storage.bank_infos()[0])
    check("点「否」不删", len(storage.bank_infos()) == before - 1, str(len(storage.bank_infos())))

    page.restore_builtin()
    app.update()
    check("恢复内置回到八份", len(storage.bank_infos()) == 8, str(len(storage.bank_infos())))
    check("列表也刷新了", len(rows(page)) == 8, str(len(rows(page))))

    print("\n[4] 自建题库对话框")
    dialog = BankPromptDialog(page, app)
    app.update()
    content = dialog.text.get("1.0", "end")
    check("对话框展示提示词", "【输出格式】" in content and "小学" in content)
    check("提示词够长", len(content) > 1200, str(len(content)))
    check("提示词里留着背景占位", "xxx 省xxx市" in content)
    check("界面提示怎么用", "背景及学习阶段" in dialog.tip_label.cget("text"), dialog.tip_label.cget("text")[:40])
    dialog.copy_prompt()
    app.update()
    check("复制进了剪贴板", "【输出格式】" in dialog.clipboard_get())
    check("按钮回执已变", dialog.copy_button.label.startswith("已复制"), dialog.copy_button.label)
    dialog.destroy()
    app.update()

    print("\n[5] 重启后状态还在")
    app.on_close(force=True)

    app2 = App()
    app2.update()
    app2.set_page("bank")
    app2.update()
    # 删掉的那份在恢复后不会自动重新加入出题范围——留着 7 份是预期行为，
    # 家长想让它回来再点一下开关即可
    check("参与出题的份数被记住", len(app2.storage.selected_banks()) == 7, str(app2.storage.state["quiz_banks"]))
    check("恢复的题库默认不参与", len(rows(app2.pages["bank"])) == 8, str(len(rows(app2.pages["bank"]))))

    print("\n[6] 错题库在列表里的样子")
    from quizwin.core.models import Question  # noqa: E402
    from quizwin.core.wrongbook import WRONG_FILE  # noqa: E402

    page2 = app2.pages["bank"]
    app2.storage.wrong_book.add(
        Question({"type": "single", "q": "错题一号", "a": ["甲", "乙"], "k": 0, "subject": "数学"})
    )
    app2.storage.set_bank_selected(WRONG_FILE, True)
    page2.reload_bank_list()
    page2.refresh_table()
    app2.update()
    check("列表里多出「错题库」", len(rows(page2)) == 9, str(len(rows(page2))))
    wrong_row = next((r for r in rows(page2) if r.info.filename == WRONG_FILE), None)
    check("找到了错题库那一行", wrong_row is not None)
    check("默认参与出题", WRONG_FILE in page2.selected_names(), str(page2.selected_names()))

    page2.switch_bank(wrong_row.info)
    app2.update()
    check("能打开错题库", app2.engine.bank.path.name == WRONG_FILE, str(app2.engine.bank.path))
    check("副标题说明是自动收集", "答错自动收集" in page2.meta_label.cget("text"), page2.meta_label.cget("text"))
    check("露出「清空错题库」", bool(page2.clear_wrong.winfo_manager()))

    app2.set_page("quiz")
    app2.set_page("bank")
    app2.update()
    check("换页回来按钮还在", bool(page2.clear_wrong.winfo_manager()))

    other = next(info for info in app2.storage.bank_infos() if info.filename != WRONG_FILE)
    page2.switch_bank(other)
    app2.update()
    check("换成别的题库按钮收起", not page2.clear_wrong.winfo_manager())

    page2.switch_bank(wrong_row.info)
    app2.update()
    with mock.patch("quizwin.ui.page_bank.messagebox.askyesno", return_value=False):
        page2.clear_wrong_book()
    check("点「否」不清空", app2.storage.wrong_book.count() == 1, str(app2.storage.wrong_book.count()))
    with mock.patch("quizwin.ui.page_bank.messagebox.askyesno", return_value=True):
        page2.clear_wrong_book()
    app2.update()
    check("确认后清空", app2.storage.wrong_book.count() == 0, str(app2.storage.wrong_book.count()))
    check("清空后表格显示 0 题", "共 0 题" in page2.meta_label.cget("text"), page2.meta_label.cget("text"))

    app2.on_close(force=True)

    print()
    if FAILURES:
        print("失败：", "；".join(FAILURES))
        return 1
    print("题库界面冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
