; 题了个题 · 桌面版 —— NSIS 安装脚本
;
; 设计取舍：
;   1. 装到 %LOCALAPPDATA%\Programs，RequestExecutionLevel user —— 双击即装，不弹 UAC，
;      公司/学校电脑没有管理员权限也能装。
;   2. 卸载项写 HKCU，出现在「应用和功能」里，可正常卸载。
;   3. 卸载时单独询问是否删除孩子数据，默认不删（误删进度是最气人的事）。
;
; 编译：python build_installer.py

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APP_NAME "题了个题"
!define APP_VERSION "0.3.1"
!define APP_EXE "题了个题.exe"
!define APP_REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\题了个题"
!define APP_DATA "$LOCALAPPDATA\题了个题"
!define SRC_DIR "..\dist\题了个题"

Name "${APP_NAME} ${APP_VERSION}"
BrandingText "${APP_NAME} ${APP_VERSION}"
OutFile "..\dist\${APP_NAME}-${APP_VERSION}-安装版.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "${APP_REGKEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
CRCCheck on
XPStyle on

VIProductVersion "0.3.1.0"
VIAddVersionKey /LANG=2052 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APP_NAME} 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "仅本地使用，不联网"
VIAddVersionKey /LANG=2052 "OriginalFilename" "${APP_NAME}-${APP_VERSION}-安装版.exe"

; ---------------------------------------------------------------- 界面

!define MUI_ICON "app.ico"
!define MUI_UNICON "app.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEFINISHPAGE_BITMAP "welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "header.bmp"
!define MUI_WELCOMEPAGE_TITLE "安装 ${APP_NAME}"
!define MUI_WELCOMEPAGE_TEXT "这是一个本地答题程序，不联网、不上传任何数据。$\r$\n$\r$\n安装完成后：$\r$\n  · 程序装进个人目录，不需要管理员权限$\r$\n  · 答题进度与家长密码保存在本机$\r$\n  · 可从「设置 → 应用」正常卸载$\r$\n$\r$\n点「下一步」继续。"

!define MUI_DIRECTORYPAGE_TEXT_TOP "程序将安装到下面的文件夹。这个位置在个人目录下，不需要管理员权限；点「浏览」可以换到别处（比如 U 盘）。"

!define MUI_FINISHPAGE_TITLE "安装完成"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${APP_NAME}"
!define MUI_FINISHPAGE_TEXT "第一次运行会全屏要求设置家长密码，设好立刻进入答题锁屏：答够时长才解锁电脑，到点自动锁回来。$\r$\n$\r$\n答题进度和密码只存在这台电脑上，不联网、不上传。"

!define MUI_UNCONFIRMPAGE_TEXT_TOP "将卸载 ${APP_NAME}。卸载过程中会单独询问是否删除答题进度与家长密码，默认保留。"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

; ---------------------------------------------------------------- 安装

Section "主程序（必需）" SEC_CORE
  SectionIn RO
  SetOutPath "$INSTDIR"
  ; 覆盖安装前先请用户关掉正在运行的实例，否则文件被占用会装一半
  IfFileExists "$INSTDIR\${APP_EXE}" 0 install_files
  FindWindow $0 "" "${APP_NAME} · 桌面版"
  StrCmp $0 0 install_files
  MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "${APP_NAME} 正在运行，请先退出（家长可在程序里点退出），再点「确定」继续安装。" IDOK install_files
  Abort

  install_files:
  File /r "${SRC_DIR}\*.*"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"

  WriteRegStr HKCU "${APP_REGKEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${APP_REGKEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${APP_REGKEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${APP_REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${APP_REGKEY}" "Publisher" "本地自用"
  WriteRegStr HKCU "${APP_REGKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${APP_REGKEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKCU "${APP_REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${APP_REGKEY}" "NoRepair" 1

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${APP_REGKEY}" "EstimatedSize" "$0"
SectionEnd

Section "创建桌面快捷方式" SEC_DESKTOP
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

Section "开机自动启动（建议）" SEC_STARTUP
  CreateShortCut "$SMSTARTUP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE} "答题程序本体，约 25 MB。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} "在桌面上放一个图标。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_STARTUP} "开机就启动程序，孩子开机第一眼看到的是答题锁屏——家长控制要靠它才管得住。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; 完成页「立即运行」：显式 Exec，比 MUI 内置钩子在中文路径下更稳
Function LaunchApp
  ExecShell "open" "$INSTDIR\${APP_EXE}"
  ; 安装器立刻退出会打断刚起步的进程（PyInstaller 还在加载 DLL），等它站稳再走
  Sleep 2000
FunctionEnd

; ---------------------------------------------------------------- 卸载

Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMSTARTUP\${APP_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_NAME}"
  DeleteRegKey HKCU "${APP_REGKEY}"

  ; 数据单独问一次，默认不删
  IfFileExists "${APP_DATA}\data\state.json" 0 remove_program
  MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除答题进度、题库修改和家长密码？$\r$\n$\r$\n位置：${APP_DATA}$\r$\n$\r$\n选「否」则保留数据，以后重装还能接着用。" IDNO remove_program
  RMDir /r "${APP_DATA}"

  remove_program:
  RMDir /r "$INSTDIR"
SectionEnd
