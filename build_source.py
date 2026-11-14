"""把源码打成一个 zip（dist\\题了个题-0.3.6-源码版.zip）。

收什么由版本库定义，不用手工维护白名单：
  * 只收 `git ls-files` 列出的文件，所以 state.json、__pycache__、截图中间产物、
    dist 里的 exe 这些天然进不来，也不会因为将来新增目录而漏收；
  * 未提交的改动同样不进包——包与提交一一对应，拿到 zip 的人能在 GitHub 上
    找到同一份代码。

包里另外塞一份「源码版说明.txt」（仓库里没有这份文件），写给只是拿到 zip 的人。

用法：
    python build_source.py

顺序有讲究：build_package.py 会先 rmtree(dist)，所以本脚本必须最后跑。
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
APP_NAME = "题了个题"
VERSION_INFO = ROOT / "build" / "version_info.txt"
REPO_URL = "https://github.com/shushanwz/studyontv-win"
UPSTREAM_URL = "https://github.com/chadyi/StudyOnTV"

# 打包后不该出现的东西。命中即报错，宁可停下也不出一份夹带私货的包。
FORBIDDEN = (
    "state.json",
    "error.log",
    "unlock.flag",
    "__pycache__",
    ".pyc",
    ".bmp",
    "_scratch",
    "dist/",
    ".git/",
    "runtime/",
    "trash/",
)

README = """\
题了个题 · 桌面版 —— 源码版 v{version}
========================================

这是源码，不是安装包。只想用、不想碰 Python 的，去下「{app}-{version}-安装版.exe」。

一、运行要求
    Windows 10 / 11，Python 3.9 及以上（本机实测 3.13），需要带 tkinter。
    零第三方依赖：不用 pip install 任何东西，程序不联网。

二、怎么跑
    双击「启动.bat」        自动挑一个带 tkinter 的 Python，用 pythonw 启动，不留黑窗
    双击「调试启动.bat」    带控制台，报错看得见，改代码时用这个
    命令行                  python run.py

三、第一次运行会发生什么
    1. 把内置题库铺到 data\\banks\\（8 份，语文数学英语历史其他常识安全诗歌）
    2. 全屏要求设置家长密码；不设就退出程序
    3. 进度与设置写在 data\\state.json，删掉这个文件等于重置

    data\\ 是程序自己的数据目录。装成安装版之后它在 %LOCALAPPDATA%\\题了个题\\
    下，源码运行时就在本目录——同一个 data 目录放一个空的 portable.flag 也能强制
    走便携模式，见 README 第八节。

四、目录里有什么
    run.py              程序入口（--guard / --force-lock 是看门狗内部参数，不用手敲）
    quizwin\\            全部源码
      core\\             引擎、存储、锁、规则、错题库、静音
      ui\\               tkinter 界面：答题、题库、家长控制、关于、锁屏、计时条
      winapi\\           Win32 调用：DPI 感知、输入封锁、系统静音
    data\\banks\\         内置题库 JSON，可直接编辑，界面上也能导入导出
    tests\\              十四套冒烟测试
    tools\\              截图与打包辅助脚本
    docs\\               家长控制方案、开发过程记录
    shots\\              README 里的截图
    build\\              打包用：NSIS 脚本、图标、版本资源

五、跑测试
        python tests\\engine_smoke.py

    十四套逐个跑，清单见 README 第九节。测试默认把数据写到临时目录
    （QUIZWIN_DATA），不会动你的 data\\state.json；涉及输入封锁的用例还要
    加 QUIZWIN_NO_GUARD=1，否则会真的锁住桌面。

六、自己打包
        python build_package.py      →  dist\\{app}\\             （要 PyInstaller）
        python build_installer.py    →  dist\\{app}-x.y.z-安装版.exe  （要 NSIS）
        python build_source.py       →  本文件所在的 zip         （要 git）

    build_package.py 会先清空 dist\\，所以它排在最前，源码版最后打。

七、这份源码从哪来
    提交    {commit}（{date}）
    仓库    {repo}
    上游    {upstream}（Kotlin / Android TV 原版，作者 chadyi）

    许可：本项目仅为个人学习使用性质的桌面复刻，不对上游任何素材主张权利，
    请勿用于商业用途。

八、已知的环境坑
    * 本机若同时装了「托管版」与「系统版」Python，PATH 上的可能不带 tkinter，
      双击「启动.bat」会自动跳过它；用命令行手工跑时注意选对解释器。
    * 高 DPI（125% / 150%）下字号是「磅」会跟着放大，改动界面的写死尺寸前先看
      README 第九节关于计时条的记录。
"""


def read_version() -> str:
    """版本号只认 build/version_info.txt 一处，免得三份文件各写各的。"""
    text = VERSION_INFO.read_text(encoding="utf-8")
    match = re.search(r"StringStruct\('FileVersion',\s*'([\d.]+)'\)", text)
    if not match:
        raise SystemExit(f"没能从 {VERSION_INFO} 里读出 FileVersion。")
    return ".".join(match.group(1).split(".")[:3])


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout


def tracked_files() -> list[str]:
    raw = subprocess.run(
        ["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True
    ).stdout
    names = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    if not names:
        raise SystemExit("git ls-files 没返回任何文件，是不是在错误的目录里跑？")
    return names


def main() -> int:
    version = read_version()
    commit = git("log", "-1", "--format=%h").strip()
    date = git("log", "-1", "--format=%ad", "--date=format:%Y-%m-%d").strip()
    stamp = time.localtime(int(git("log", "-1", "--format=%ct").strip()))

    dirty = git("status", "--porcelain").strip()
    if dirty:
        print("工作区有未提交的改动，这些改动不会进包（包里只有已提交的内容）：")
        for line in dirty.splitlines()[:10]:
            print("   ", line)
        print()

    DIST.mkdir(exist_ok=True)
    target = DIST / f"{APP_NAME}-{version}-源码版.zip"
    if target.exists():
        target.unlink()

    names = tracked_files()
    inner = f"{APP_NAME}-{version}-源码"
    readme = README.format(
        version=version,
        app=APP_NAME,
        commit=commit,
        date=date,
        repo=REPO_URL,
        upstream=UPSTREAM_URL,
    )

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            source = ROOT / name
            if not source.is_file():
                print(f"跳过（磁盘上已不存在）：{name}")
                continue
            # 时间戳统一取提交时间：同一份代码打两次，包内容一致
            info = zipfile.ZipInfo(f"{inner}/{name}", date_time=stamp)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes())

        info = zipfile.ZipInfo(f"{inner}/源码版说明.txt", date_time=stamp)
        info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        # 带 BOM：Windows 记事本与 VS Code 都不会把中文认成乱码
        archive.writestr(info, ("\ufeff" + readme.replace("\n", "\r\n")).encode("utf-8"))

    return verify(target, names, inner)


def verify(target: Path, names: list[str], inner: str) -> int:
    """打完之后自己再开一遍，确认该在的都在、不该在的都没混进来。"""
    with zipfile.ZipFile(target) as archive:
        entries = archive.namelist()
        bad = [item for item in entries if any(word in item for word in FORBIDDEN)]
        problems: list[str] = []
        if bad:
            problems.append("夹带了不该进包的文件：" + "、".join(bad[:5]))

        required = [
            "run.py",
            "启动.bat",
            "README.md",
            "源码版说明.txt",
            "quizwin/ui/app.py",
            "quizwin/core/engine.py",
            "data/banks",
        ]
        for item in required:
            if not any(entry.startswith(f"{inner}/{item}") for entry in entries):
                problems.append(f"缺了必需文件：{item}")

        banks = [entry for entry in entries if entry.startswith(f"{inner}/data/banks/")]
        if len(banks) < 8:
            problems.append(f"内置题库只有 {len(banks)} 份，应该是 8 份")

        if problems:
            print("包不合格：")
            for line in problems:
                print("   -", line)
            target.unlink(missing_ok=True)
            return 1

    size = target.stat().st_size / 1024 / 1024
    print(f"源码包：{target}")
    print(f"体积：{size:.1f} MB，{len(entries)} 个文件（其中题库 {len(banks)} 份）")
    print(f"对应提交：{git('log', '-1', '--format=%h %s').strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
