"""锁屏静音：锁屏那一刻关掉系统声音，解锁时只还原自己动过的那次。

三个约定：

1. **只还自己欠的账。** 锁屏前若本来就是静音（家长自己关的），记号里写 1，
   解锁时不动它——否则程序会把人家静着的声音打开，比不静音更冒犯。
2. **记在盘上，不只记在内存。** 静音是全局系统状态，程序被杀、蓝屏、断电后
   不会自己恢复。记号落在 state.json 里，下次启动 recover() 能收拾干净。
3. **绝不因为静音失败影响锁屏。** 声卡缺失、接口变动都只记一句日志，
   锁屏照常进行（静音只是锦上添花，锁住电脑才是本职）。
"""

from __future__ import annotations

import os

from ..winapi.audio import SystemAudio

KEY = "muteBefore"  # None = 本程序没动过声音；0/1 = 动过，值为动之前的原始状态


class NullAudio:
    """假后端：只记账，不碰真声音。

    自动化测试会一路跑到「回锁」这一步，若用真后端，跑一次测试就把用户电脑
    静音了——测试结束进程退出，再没人来还原。凡是设了 QUIZWIN_NO_GUARD
    （测试统一入口）或 QUIZWIN_NO_AUDIO 时都换成它。
    """

    def __init__(self, start_muted: bool = False) -> None:
        self.muted = start_muted
        self.calls: list[bool] = []

    def is_muted(self) -> bool:
        return self.muted

    def set_mute(self, muted: bool) -> bool:
        self.calls.append(bool(muted))
        self.muted = bool(muted)
        return True


def _offline() -> bool:
    return os.environ.get("QUIZWIN_NO_GUARD") == "1" or os.environ.get("QUIZWIN_NO_AUDIO") == "1"


class MuteGuard:
    def __init__(self, lock, backend=None) -> None:
        self.lock = lock
        self._audio = backend or (NullAudio() if _offline() else SystemAudio())
        self.last_error = ""

    # ---------- 记号 ----------

    @property
    def _cfg(self) -> dict:
        return self.lock.cfg

    def engaged(self) -> bool:
        """本程序当前是否「欠着一笔」未还原的静音。"""
        return self._cfg.get(KEY) is not None

    def _remember(self, value) -> None:
        self._cfg[KEY] = value
        try:
            self.lock.st.save_state()
        except OSError as exc:  # 盘满、权限异常：声音照管，记号丢了也能靠 recover 兜一部分
            self.last_error = f"状态保存失败：{exc}"

    # ---------- 动作 ----------

    def engage(self) -> str:
        """锁屏时调用。返回 muted / already / unsupported / failed。"""
        if self.engaged():
            return "already"  # 幂等：重复锁屏不再动第二次
        current = self._audio.is_muted()
        if current is None:
            self.last_error = self._audio.last_error or "无法读取系统音量"
            return "unsupported"
        if current:
            # 本来就静音：只记一笔「未静音时该还原成什么」的反面，即保持静音
            self._remember(1)
            return "already"
        if not self._audio.set_mute(True):
            self.last_error = self._audio.last_error or "静音失败"
            return "failed"
        self._remember(0)
        return "muted"

    def release(self) -> bool:
        """解锁时调用（也在退出与启动兜底里用）。返回是否真的改动了系统声音。"""
        before = self._cfg.get(KEY)
        if before is None:
            return False
        # 先清记号再动声音：万一 SetMute 抛错，也不会留下一个「永远还原不了」的残记
        self._remember(None)
        if int(before) == 0:
            return self._audio.set_mute(False)
        return False

    def recover(self) -> bool:
        """启动兜底：上次没走完 release（崩溃、断电、直接拔电）就把声音还回去。"""
        if not self.engaged():
            return False
        return self.release()

    def status_text(self) -> str:
        if not self.engaged():
            return "未静音"
        return "已静音" if int(self._cfg.get(KEY) or 0) == 0 else "原本静音"
