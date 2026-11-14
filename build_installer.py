"""用 NSIS 把 dist\\题了个题\\ 打成安装包 dist\\题了个题-0.3.5-安装版.exe。

前置：
  1. 先跑 build_package.py，生成 dist\\题了个题\\；
  2. NSIS 解压在 build\\tools\\nsis\\nsis-3.11（makensis.exe 所在）。

为什么用 NSIS 而不是 Inno Setup：
  - Inno Setup 的安装程序只有 GitHub 直链可用，本机代理取不下来；
  - NSIS 有 SourceForge 的绿色 zip，解压即用，不往系统里装东西；
  - 40 KB 的安装器体积，支持中文向导、组件选择、静默安装与卸载项。

用法：python build_installer.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
APP_NAME = "题了个题"
VERSION = "0.3.5"
PAYLOAD = DIST / APP_NAME
SCRIPT = BUILD / "installer.nsi"
OUTPUT = DIST / f"{APP_NAME}-{VERSION}-安装版.exe"

MAKENSIS_CANDIDATES = [
    BUILD / "tools" / "nsis" / "nsis-3.11" / "makensis.exe",
    Path(r"C:\Program Files (x86)\NSIS\makensis.exe"),
    Path(r"C:\Program Files\NSIS\makensis.exe"),
]


def find_makensis() -> Path:
    for path in MAKENSIS_CANDIDATES:
        if path.exists():
            return path
    raise SystemExit("找不到 makensis.exe，请把 NSIS 解压到 build\\tools\\nsis\\nsis-3.11。")


def ensure_utf8_bom(path: Path) -> None:
    """NSIS 只认带 BOM 的 UTF-8 脚本，否则中文全变乱码。"""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return
    path.write_bytes(b"\xef\xbb\xbf" + data)


def main() -> int:
    if not (PAYLOAD / f"{APP_NAME}.exe").exists():
        print(f"没有找到 {PAYLOAD / (APP_NAME + '.exe')}，请先运行 build_package.py。")
        return 1

    makensis = find_makensis()
    ensure_utf8_bom(SCRIPT)

    if OUTPUT.exists():
        OUTPUT.unlink()

    cmd = [str(makensis), "/V2", str(SCRIPT)]
    print("执行：", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(BUILD))
    if result.returncode != 0:
        print("编译失败。")
        return result.returncode

    if not OUTPUT.exists():
        print(f"没有生成 {OUTPUT}，请检查 NSIS 输出。")
        return 1

    size = OUTPUT.stat().st_size / 1024 / 1024
    print()
    print(f"安装包：{OUTPUT}")
    print(f"体积：{size:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
