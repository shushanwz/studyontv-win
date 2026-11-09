"""键盘拦截自检：装 20 秒钩子，统计吞掉了哪些组合，到点自动卸载。

为什么需要手动跑：能不能真拦住 Alt+Tab，机器验不了——得有人真按一下。

用法：
    python tools/harden_probe.py          # 跑 20 秒
    python tools/harden_probe.py 30       # 跑 30 秒

这 20 秒里请依次按：Win、Alt+Tab、Alt+F4、Ctrl+Esc、Ctrl+Shift+Esc。
按完之后看输出的计数，以及窗口有没有被切走。
到点自动卸载，不会留下钩子。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quizwin.winapi.harden import HardenOptions, Hardening  # noqa: E402


def main(argv: list[str]) -> int:
    seconds = 20
    for arg in argv:
        if arg.isdigit():
            seconds = max(5, min(120, int(arg)))

    print("=" * 52)
    print("键盘拦截自检")
    print("=" * 52)
    print("接下来 20 秒内，请依次按：")
    print("  Win 键 / Alt+Tab / Alt+F4 / Ctrl+Esc / Ctrl+Shift+Esc")
    print("每按一次，下面的计数会加一；窗口如果被切走，说明没拦住。")
    print()

    hard = Hardening(lambda: 0, HardenOptions(keyboard_hook=True, clip_cursor=False, keep_foreground=False))
    if not hard.install():
        print("钩子安装失败：", hard.last_error)
        return 1

    start = time.time()
    last = 0
    try:
        while time.time() - start < seconds:
            time.sleep(0.5)
            if hard.stats["swallowed"] != last:
                last = hard.stats["swallowed"]
                print(f"  已吞下 {last} 次按键（{time.time() - start:.1f}s）")
    except KeyboardInterrupt:
        pass
    finally:
        hard.uninstall()

    total = hard.stats["swallowed"]
    print()
    print(f"共吞下 {total} 次按键，钩子已卸载。")
    if total == 0:
        print("一次都没吞到：要么没按，要么钩子被安全软件拦了。")
    else:
        print("计数在涨，说明组合键已被拦在系统之前。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
