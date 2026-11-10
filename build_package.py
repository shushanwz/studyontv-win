"""把程序打成免安装的 exe 目录（dist\\题了个题\\）。

为什么要 onedir 而不是 onefile：
  - onefile 每次启动都要把几十兆解包到临时目录，冷启动 3–5 秒；
  - onedir 直接运行，1 秒内出界面；
  - 杀毒软件对 onefile 自解压行为更敏感，误报率高。

安装包（setup.exe）由 build\\installer.iss 用 Inno Setup 编译，见 build_installer.py。

用法（必须用带 tkinter 的 Python）：
    python build_package.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
APP_NAME = "题了个题"

SPEC = r'''# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    [r"{root}\run.py"],
    pathex=[r"{root}"],
    binaries=[],
    datas=[(r"{root}\data\banks", r"data\banks")],
    hiddenimports=collect_submodules("quizwin"),
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        "PIL", "numpy", "pandas", "matplotlib", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "setuptools", "pip", "unittest", "pydoc",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="{name}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[r"{root}\build\app.ico"],
    version=r"{root}\build\version_info.txt",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="{name}",
)
'''


def check_tkinter() -> None:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("当前解释器没有 tkinter，打出来的程序会开不了界面。")
        print(f"解释器：{sys.executable}")
        print(r"请改用：C:\Users\<用户>\AppData\Local\Programs\Python\Python313\python.exe")
        raise SystemExit(1)


def main() -> int:
    check_tkinter()
    BUILD.mkdir(exist_ok=True)

    spec_path = BUILD / "_generated.spec"
    spec_path.write_text(
        SPEC.format(root=str(ROOT).replace("\\", "\\\\"), name=APP_NAME),
        encoding="utf-8",
    )

    if DIST.exists():
        shutil.rmtree(DIST)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--log-level",
        "WARN",
        str(spec_path),
    ]
    print("执行：", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("打包失败。")
        return result.returncode

    target = DIST / APP_NAME
    exe = target / f"{APP_NAME}.exe"
    if not exe.exists():
        print(f"没有找到 {exe}，请查看上面的输出。")
        return 1

    total = sum(item.stat().st_size for item in target.rglob("*") if item.is_file())
    print()
    print(f"打包完成：{exe}")
    print(f"目录体积：{total / 1024 / 1024:.1f} MB（{len(list(target.rglob('*')))} 个条目）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
