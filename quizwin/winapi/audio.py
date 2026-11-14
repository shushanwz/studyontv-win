"""系统静音开关（Windows Core Audio）。

只用 ctypes 调 COM，零第三方依赖，也不改注册表、不装驱动。

为什么走 COM 而不是模拟音量键（keybd_event VK_VOLUME_MUTE）：
  * 音量键是「翻转」语义，按两次才回到原状。程序崩溃、被重复调用时都会乱；
  * 翻转前拿不到当前状态，没法在解锁时判断「该不该恢复」，只能盲按。
Core Audio 的 IAudioEndpointVolume 有 GetMute/SetMute，可读可写、幂等，
才能做到「锁屏关掉、解锁只还原自己动过的那次」。

失败一律返回 None / False，绝不抛异常：静音是附加功能，不能因为声卡没装好
把锁屏流程带崩。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, byref, c_int, c_uint, c_ubyte, c_ushort, c_void_p

HRESULT = ctypes.c_long

# CLSCTX_ALL：拿设备时不必细究是进程内还是跨进程
CLSCTX_ALL = 0x17

# 数据流方向：eRender = 0（放音），角色：eConsole = 0（默认播放设备）
E_RENDER = 0
E_CONSOLE = 0


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", c_uint),
        ("Data2", c_ushort),
        ("Data3", c_ushort),
        ("Data4", c_ubyte * 8),
    ]


_CLSID_MMDEVICE_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDEVICE_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAUDIO_ENDPOINT_VOLUME = "{5CDF2C82-841E-4546-9722-0CF74078229A}"

# vtable 序号（IUnknown 占 0-2，其余按接口声明顺序）
_VT_RELEASE = 2
_VT_ENUM_GET_DEFAULT_ENDPOINT = 4          # IMMDeviceEnumerator::GetDefaultAudioEndpoint
_VT_DEVICE_ACTIVATE = 3                     # IMMDevice::Activate
_VT_VOLUME_SET_MUTE = 14                    # IAudioEndpointVolume::SetMute
_VT_VOLUME_GET_MUTE = 15                    # IAudioEndpointVolume::GetMute


def _guid(text: str) -> _GUID:
    value = _GUID()
    ole32 = ctypes.windll.ole32
    if ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(value)) != 0:
        raise OSError(f"GUID 解析失败：{text}")
    return value


def _vtbl(ptr: c_void_p, index: int, restype, argtypes):
    """取 COM 对象的第 index 个虚函数，并绑定成可调用对象。"""
    table = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(table[index])


def _release(ptr: c_void_p) -> None:
    if ptr:
        try:
            _vtbl(ptr, _VT_RELEASE, ctypes.c_ulong, [])(ptr)
        except Exception:
            pass


class SystemAudio:
    """默认播放设备的静音开关。每次调用都重新取端点，避免缓存住已拔掉的声卡。"""

    def __init__(self) -> None:
        self.last_error = ""

    # ---------- 内部 ----------

    @staticmethod
    def _supported() -> bool:
        return sys.platform == "win32"

    def _with_volume(self, action):
        """取到 IAudioEndpointVolume 后执行 action，随后统一释放。

        返回 (成功与否, action 的返回值)。任何一步失败都返回 (False, None)。
        """
        if not self._supported():
            self.last_error = "仅支持 Windows"
            return False, None

        self.last_error = ""
        ole32 = ctypes.windll.ole32
        # 主线程通常已被 Tk 初始化过 COM，这里重复初始化只会拿到 S_FALSE，无副作用
        ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        enumerator = c_void_p()
        device = c_void_p()
        volume = c_void_p()
        try:
            clsid = _guid(_CLSID_MMDEVICE_ENUMERATOR)
            iid = _guid(_IID_IMMDEVICE_ENUMERATOR)
            hr = ole32.CoCreateInstance(
                byref(clsid), None, CLSCTX_ALL, byref(iid), byref(enumerator)
            )
            if hr != 0 or not enumerator:
                self.last_error = f"CoCreateInstance 失败（0x{hr & 0xFFFFFFFF:08X}）"
                return False, None

            hr = _vtbl(
                enumerator, _VT_ENUM_GET_DEFAULT_ENDPOINT, HRESULT,
                [c_int, c_int, POINTER(c_void_p)],
            )(enumerator, E_RENDER, E_CONSOLE, byref(device))
            if hr != 0 or not device:
                # 常见于没有可用播放设备（无声卡、HDMI 独占、远程会话）
                self.last_error = f"取默认播放设备失败（0x{hr & 0xFFFFFFFF:08X}）"
                return False, None

            volume_iid = _guid(_IID_IAUDIO_ENDPOINT_VOLUME)
            hr = _vtbl(
                device, _VT_DEVICE_ACTIVATE, HRESULT,
                [POINTER(_GUID), c_uint, c_void_p, POINTER(c_void_p)],
            )(device, byref(volume_iid), CLSCTX_ALL, None, byref(volume))
            if hr != 0 or not volume:
                self.last_error = f"取音量接口失败（0x{hr & 0xFFFFFFFF:08X}）"
                return False, None

            return True, action(volume)
        except OSError as exc:
            self.last_error = str(exc)
            return False, None
        except Exception as exc:  # pragma: no cover - COM 层异常形状不确定
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False, None
        finally:
            _release(volume)
            _release(device)
            _release(enumerator)

    # ---------- 对外 ----------

    def is_muted(self) -> bool | None:
        """当前是否静音。拿不到设备时返回 None（区别于「未静音」）。"""
        def read(volume):
            value = c_int()
            hr = _vtbl(volume, _VT_VOLUME_GET_MUTE, HRESULT, [POINTER(c_int)])(volume, byref(value))
            if hr != 0:
                self.last_error = f"GetMute 失败（0x{hr & 0xFFFFFFFF:08X}）"
                return None
            return bool(value.value)

        ok, result = self._with_volume(read)
        return bool(result) if ok and result is not None else None

    def set_mute(self, muted: bool) -> bool:
        """设置静音，返回是否成功。"""
        def write(volume):
            hr = _vtbl(
                volume, _VT_VOLUME_SET_MUTE, HRESULT, [c_int, c_void_p]
            )(volume, 1 if muted else 0, None)
            if hr != 0:
                self.last_error = f"SetMute 失败（0x{hr & 0xFFFFFFFF:08X}）"
                return False
            return True

        ok, result = self._with_volume(write)
        return bool(ok and result)


if __name__ == "__main__":  # 手工验证：python -m quizwin.winapi.audio
    audio = SystemAudio()
    print("可用 :", audio._supported())
    print("当前静音状态:", audio.is_muted())
    print("错误 :", audio.last_error or "无")
