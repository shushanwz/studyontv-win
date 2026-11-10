"""程序路径：源码运行与打包安装后运行，共用一套判定。

三条规则，从高到低：

1. 环境变量 `QUIZWIN_DATA` 指哪儿，数据就写哪儿（测试与高级用法）；
2. 打包版旁边放了 `portable.flag`，且该目录可写 → 数据放程序目录（便携，整个文件夹拷走即可带走）；
3. 其余情况 → `%LOCALAPPDATA%\\题了个题\\data`。

为什么默认不写程序目录：安装包默认装进 `C:\\Program Files`，那里普通用户
没有写权限。老版本把 `data/` 放在程序目录，装到 Program Files 后连进度都存不下。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "题了个题"
PORTABLE_FLAG = "portable.flag"


def is_frozen() -> bool:
    """是否由 PyInstaller 打包后运行。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """可执行文件所在目录；源码运行时为项目根目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundle_dir() -> Path:
    """随程序分发的资源目录。onefile 模式下是临时解包目录。"""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else app_dir()


def _probe_writable(path: Path) -> bool:
    """真写一次文件再删，比 os.access 可靠——Windows 上后者对 ACL 判断不准。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def default_data_dir() -> Path:
    """数据目录（不创建，由调用方决定何时落地）。"""
    override = os.environ.get("QUIZWIN_DATA")
    if override:
        return Path(override)

    if not is_frozen():
        # 源码运行：仍用项目里的 data/，方便调试与备份
        return app_dir() / "data"

    portable = app_dir() / PORTABLE_FLAG
    if portable.exists() and _probe_writable(app_dir() / "data"):
        return app_dir() / "data"

    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / APP_NAME / "data"


def builtin_banks_dir() -> Path:
    """随程序分发的题库目录。源码运行时就是项目里的 data/banks。"""
    return bundle_dir() / "data" / "banks"


def builtin_bank_files() -> list[Path]:
    source = builtin_banks_dir()
    return sorted(source.glob("*.json")) if source.is_dir() else []


def restore_builtin(target: Path, skip: set[str] | None = None) -> list[str]:
    """把内置题库里「缺失的」逐份补进 target/banks，返回补进来的文件名。

    逐份比对而不是「只补空目录」——这样删掉一份、留着其余，下次启动也只补
    缺的那份，不会把用户删掉的题库整批复活（要复活请走 skip 之外的显式恢复）。
    同名文件一律不覆盖：用户改过的内容优先级最高。
    """
    created: list[str] = []
    skip = set(skip or ())
    try:
        banks = target / "banks" if target.name != "banks" else target
        source = builtin_banks_dir()
        if not source.is_dir():
            return created
        if source.resolve() == banks.resolve():
            return created  # 源码运行，源就是目标
        banks.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.glob("*.json")):
            if item.name in skip:
                continue
            destination = banks / item.name
            if not destination.exists():
                shutil.copyfile(item, destination)
                created.append(item.name)
    except OSError:
        pass
    return created


def seed_data(target: Path) -> list[str]:
    """首次运行把随程序分发的题库复制过去（等价于全量恢复）。"""
    return restore_builtin(target)


def legacy_data_dir() -> Path:
    """老版本（数据写在程序目录）的位置，用于一次性迁移提示。"""
    return app_dir() / "data"
