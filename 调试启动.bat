@echo off
chcp 936 >nul
rem 带命令行窗口启动，出错时能看到完整堆栈，排查问题用
call "%~dp0启动.bat" debug
