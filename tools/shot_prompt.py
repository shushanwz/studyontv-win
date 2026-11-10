"""截「自建题库」对话框（只截对话框本身，不带桌面）。

用法： python tools\\shot_prompt.py [输出路径]
"""

import ctypes
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from PIL import ImageGrab  # noqa: E402

from quizwin.ui.app import App  # noqa: E402
from quizwin.ui.bank_prompt import BankPromptDialog  # noqa: E402

user32 = ctypes.windll.user32
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "shots" / "16-AI自建题库.png"

app = App(lock_mode=False)
app.geometry("1240x760+40+20")
app.attributes("-topmost", True)


def shoot() -> None:
    app.set_page("bank")
    dialog = BankPromptDialog(app.pages["bank"], app)
    dialog.attributes("-topmost", True)
    dialog.update()
    time.sleep(0.8)
    dialog.update()

    hwnd = user32.GetParent(dialog.winfo_id()) or dialog.winfo_id()
    raw = ctypes.create_string_buffer(16)
    user32.GetWindowRect(hwnd, raw)
    left, top, right, bottom = struct.unpack("4i", raw.raw)
    print("dialog rect", left, top, right, bottom, right - left, bottom - top)
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(out)
    print("saved", out)
    dialog.destroy()
    app.destroy()


app.after(700, shoot)
app.mainloop()
