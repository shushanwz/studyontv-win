"""Windows 系统层：锁屏期间真正拦住输入与窗口切换。

这里只做三件事，全部在用户态，不写驱动：
1. 低级键盘钩子（WH_KEYBOARD_LL）：吞掉 Win / Alt+Tab / Alt+F4 / Alt+Esc /
   Ctrl+Esc / Ctrl+Shift+Esc。
2. 鼠标裁剪（ClipCursor）：把光标锁在主屏内。
3. 置顶抢占（SetWindowPos + SetForegroundWindow）：防止窗口被压下去。

装与卸必须成对：只有锁屏窗口存在时才装，解锁的一瞬间必须卸干净，
否则家长自己也用不了电脑。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from dataclasses import dataclass, field

IS_WINDOWS = ctypes.sizeof(ctypes.c_void_p) == 8 and hasattr(ctypes, "WinDLL")

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_F4 = 0x73
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


if IS_WINDOWS:  # pragma: no cover - 平台相关
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wt.DWORD),
            ("scanCode", wt.DWORD),
            ("flags", wt.DWORD),
            ("time", wt.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

    user32.SetWindowsHookExW.restype = wt.HHOOK
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
    user32.UnhookWindowsHookEx.restype = wt.BOOL
    user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
    user32.CallNextHookEx.restype = LRESULT
    user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.ClipCursor.argtypes = [ctypes.POINTER(wt.RECT)]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.SetWindowPos.restype = wt.BOOL
    user32.SetWindowPos.argtypes = [
        wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT
    ]
    user32.SetForegroundWindow.restype = wt.BOOL
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.GetForegroundWindow.restype = wt.HWND
    user32.BringWindowToTop.restype = wt.BOOL
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.GetParent.restype = wt.HWND
    user32.GetParent.argtypes = [wt.HWND]
    user32.SetCursorPos.restype = wt.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    # 句柄参数必须显式声明，否则 ctypes 按 32 位整数传参，64 位下会被截断
    user32.GetWindowRect.restype = wt.BOOL
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wt.DWORD, ctypes.c_void_p]
    user32.keybd_event.restype = None
    kernel32.GetCurrentThreadId.restype = wt.DWORD
else:  # pragma: no cover - 非 Windows 下仅保证可导入
    user32 = None
    kernel32 = None
    LRESULT = ctypes.c_ssize_t
    KBDLLHOOKSTRUCT = None
    HOOKPROC = ctypes.CFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


def _down(vk: int) -> bool:
    """查询某个修饰键当前是否按下。"""
    if not IS_WINDOWS:
        return False
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def block_reason(vk: int, down=_down) -> str:
    """判断这次按键该不该吞掉；返回空串表示放行。

    纯函数，便于单测。原则：只拦「切走窗口 / 关掉窗口 / 呼出系统界面」的组合，
    其余一律放行，避免影响输入答案。
    """
    if vk in (VK_LWIN, VK_RWIN):
        return "win"
    # 只要 Win 键处于按下状态，其余键一并吞掉，避免 Win+X 漏网
    if down(VK_LWIN) or down(VK_RWIN):
        return "win-combo"

    alt = down(VK_MENU) or down(VK_LMENU) or down(VK_RMENU)
    ctrl = down(VK_CONTROL) or down(VK_LCONTROL) or down(VK_RCONTROL)
    shift = down(VK_SHIFT) or down(VK_LSHIFT) or down(VK_RSHIFT)

    if alt and vk == VK_TAB:
        return "alt-tab"
    if alt and vk == VK_ESCAPE:
        return "alt-esc"
    if alt and vk == VK_F4:
        return "alt-f4"
    if ctrl and shift and vk == VK_ESCAPE:
        return "ctrl-shift-esc"
    if ctrl and vk == VK_ESCAPE:
        return "ctrl-esc"
    return ""


@dataclass
class HardenOptions:
    keyboard_hook: bool = True
    clip_cursor: bool = True
    keep_foreground: bool = True
    blocks: list[str] = field(default_factory=list)


class Hardening:
    """锁屏期间的输入封锁。安装与卸载都要幂等。"""

    def __init__(self, hwnd_provider, options: HardenOptions | None = None):
        self._hwnd_provider = hwnd_provider
        self.options = options or HardenOptions()
        self._hook = None
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._proc = None  # 必须持有回调引用，否则会被 GC 回收导致崩溃
        self._clip: tuple[int, int, int, int] | None = None
        self._lock = threading.Lock()
        self.last_error = ""
        self.stats = {"swallowed": 0, "refocus": 0}

    # ------------------------------------------------------------ 状态

    @property
    def installed(self) -> bool:
        return bool(self._hook)

    def hwnd(self) -> int:
        try:
            raw = int(self._hwnd_provider() or 0)
        except Exception:
            return 0
        if not raw or not IS_WINDOWS:
            return raw
        parent = user32.GetParent(raw)
        return int(parent or raw)

    # ------------------------------------------------------------ 装 / 卸

    def install(self) -> bool:
        if not IS_WINDOWS:
            self.last_error = "当前系统不是 Windows，输入封锁不可用"
            return False
        with self._lock:
            if self._hook:
                return True
            if self.options.keyboard_hook:
                if not self._start_hook():
                    return False
        if self.options.clip_cursor:
            self.clip()
        if self.options.keep_foreground:
            self.keep_foreground()
        return True

    def uninstall(self) -> None:
        with self._lock:
            self._stop_hook()
            self._release_clip()
        self._clip = None

    # ------------------------------------------------------------ 键盘钩子

    def _start_hook(self) -> bool:
        if not IS_WINDOWS:
            return False

        def hook_body(n_code, w_param, l_param):
            if n_code < 0:
                return user32.CallNextHookEx(None, n_code, w_param, l_param)
            try:
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
                    info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if block_reason(int(info.vkCode)):
                        self.stats["swallowed"] += 1
                        # 按下与抬起都吞，避免系统留下「Win 键卡住」的状态
                        return 1
            except Exception:
                # 回调里绝不能抛异常：会把整条输入链拖死
                pass
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc = HOOKPROC(hook_body)
        ready = threading.Event()
        result: dict[str, object] = {}

        def runner():
            self._thread_id = int(kernel32.GetCurrentThreadId())
            handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
            result["handle"] = handle
            if not handle:
                self.last_error = f"键盘钩子安装失败（错误码 {ctypes.get_last_error()}）"
                ready.set()
                return
            ready.set()
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        self._thread = threading.Thread(target=runner, name="quizwin-keyhook", daemon=True)
        self._thread.start()
        ready.wait(2.0)
        handle = result.get("handle")
        if not handle:
            self._thread = None
            self._proc = None
            return False
        self._hook = handle
        return True

    def _stop_hook(self) -> None:
        if not self._hook:
            return
        try:
            user32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass
        if self._thread_id:
            try:
                user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        self._hook = None
        self._thread = None
        self._thread_id = 0
        self._proc = None

    # ------------------------------------------------------------ 鼠标与焦点

    def clip(self) -> None:
        """把光标限制在锁屏窗口范围内。多显示器下只锁主屏。"""
        if not IS_WINDOWS or not self.options.clip_cursor:
            return
        hwnd = self.hwnd()
        if not hwnd:
            return
        rect = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return
        box = wt.RECT(rect.left, rect.top, rect.right, rect.bottom)
        try:
            user32.ClipCursor(ctypes.byref(box))
            self._clip = (box.left, box.top, box.right, box.bottom)
        except Exception:
            pass

    def _release_clip(self) -> None:
        if IS_WINDOWS:
            try:
                user32.ClipCursor(None)
            except Exception:
                pass

    def keep_foreground(self) -> None:
        """把窗口顶回最前。被别的窗口抢走时由 pump() 反复调用。"""
        if not IS_WINDOWS or not self.options.keep_foreground:
            return
        hwnd = self.hwnd()
        if not hwnd:
            return
        try:
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            if int(user32.GetForegroundWindow() or 0) != hwnd:
                if user32.SetForegroundWindow(hwnd):
                    self.stats["refocus"] += 1
                else:
                    # 前台锁定时先用一次 Alt 击键解锁前台权限，再抢
                    for flag in (0, 2):
                        user32.keybd_event(VK_MENU, 0, flag, 0)
                    user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
        except Exception:
            pass

    def pump(self) -> None:
        """锁屏期间周期性调用：维持置顶与鼠标裁剪。"""
        if not self.installed:
            return
        self.keep_foreground()
        if self.options.clip_cursor:
            hwnd = self.hwnd()
            if hwnd:
                rect = wt.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    now = (rect.left, rect.top, rect.right, rect.bottom)
                    if now != self._clip:
                        self.clip()


# ---------------------------------------------------------------- 任务管理器

POLICY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"


def set_task_manager_disabled(disabled: bool) -> bool:
    """禁用/恢复任务管理器。只动 HKCU，不需要管理员权限。"""
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, POLICY_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            if disabled:
                winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 1)
            else:
                try:
                    winreg.DeleteValue(key, "DisableTaskMgr")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def task_manager_is_disabled() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, POLICY_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, "DisableTaskMgr")
            return bool(value)
    except Exception:
        return False
