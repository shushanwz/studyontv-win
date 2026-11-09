"""生成中文启动脚本（GBK 编码，避免 Windows 命令行乱码）。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LAUNCH = r"""@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title 题了个题 · 桌面版

if not exist "run.py" (
    echo [错误] 当前目录里没有 run.py，请把启动脚本放在程序目录中。
    echo 当前目录：%CD%
    echo.
    pause
    exit /b 1
)

set "FOUND="

rem ---- 1. PATH 上的 python ----
for /f "delims=" %%P in ('where python 2^>nul') do call :probe "%%~fP"

rem ---- 2. py 启动器指向的解释器 ----
if not defined FOUND call :probe_py

rem ---- 3. 常见安装位置 ----
if not defined FOUND for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :probe "%%~fD\python.exe"
if not defined FOUND for /d %%D in ("C:\Python3*") do call :probe "%%~fD\python.exe"
if not defined FOUND for /d %%D in ("%ProgramFiles%\Python3*") do call :probe "%%~fD\python.exe"

if not defined FOUND goto :missing

rem ---- 优先用 pythonw 启动，不留黑色命令框 ----
set "RUNNER=%FOUND%"
for %%F in ("%FOUND%") do if /i "%%~nxF"=="python.exe" if exist "%%~dpFpythonw.exe" set "RUNNER=%%~dpFpythonw.exe"

if /i "%~1"=="debug" (
    echo 解释器：%FOUND%
    "%FOUND%" "%CD%\run.py"
    echo.
    echo 退出码：%ERRORLEVEL%
    pause
    exit /b 0
)

start "" "%RUNNER%" "%CD%\run.py"
exit /b 0

:probe
if defined FOUND goto :eof
if not exist "%~1" goto :eof
"%~1" -c "import tkinter" >nul 2>nul
if errorlevel 1 goto :eof
set "FOUND=%~1"
goto :eof

:probe_py
py -3 -c "import tkinter" >nul 2>nul
if errorlevel 1 goto :eof
for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "FOUND=%%~fP"
goto :eof

:missing
echo.
echo 没有找到带 tkinter 的 Python 3。
echo.
echo 请按下面两步处理：
echo   1. 打开 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本，
echo      安装第一屏勾选 "Add python.exe to PATH"。
echo   2. 重新双击本文件。
echo.
echo 如果机器上已经装过 Python，可在命令行执行下面这行看具体报错：
echo      py -3 -c "import tkinter"
echo.
pause
exit /b 1
"""

DEBUG = r"""@echo off
chcp 936 >nul
rem 带命令行窗口启动，出错时能看到完整堆栈，排查问题用
call "%~dp0启动.bat" debug
"""


def main() -> None:
    for name, text in (("启动.bat", LAUNCH), ("调试启动.bat", DEBUG)):
        path = ROOT / name
        # CRLF + GBK：cmd.exe 在中文系统下按 936 解析批处理
        path.write_bytes(text.replace("\n", "\r\n").encode("gbk"))
        print("已写入", path, path.stat().st_size, "字节")


if __name__ == "__main__":
    main()
