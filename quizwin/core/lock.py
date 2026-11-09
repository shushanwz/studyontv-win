"""锁定状态机。

两种状态：locked（只能答题）与 unlocked（自由使用，倒计时中）。

关键约定：**不信任「已解锁」跨进程存活**。程序不在运行就等于锁着，所以重启后
一律回锁，最多记一条 abnormalExit 供家长查看。这样「杀进程 → 立刻重开」拿不到
任何便宜。

倒计时基准用 time.monotonic()（Windows 下包含睡眠时间，合上盖子也算消耗）；
同时把 wall clock 的到期时刻落盘，用于重启后与时钟回拨的判断。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from .storage import DEFAULT_LOCK, _deep_fill, _safe_int

LOCKED = "locked"
UNLOCKED = "unlocked"

REASON_TIMEUP = "timeup"
REASON_PARENT = "parent"
REASON_EXIT = "exit"
REASON_TAMPER = "tamper"
REASON_STARTUP = "startup"
REASON_MANUAL = "manual"

REASON_LABEL = {
    REASON_TIMEUP: "时间到，自动回锁",
    REASON_PARENT: "家长操作",
    REASON_EXIT: "退出程序",
    REASON_TAMPER: "检测到系统时间异常",
    REASON_STARTUP: "程序重新启动",
    REASON_MANUAL: "手动回锁",
}

# 允许的时钟回拨容差：小于这个幅度视为正常的系统校时
CLOCK_TOLERANCE = 90


class LockController:
    def __init__(self, storage, clock=None):
        self.st = storage
        self._clock = clock or time.monotonic
        self._deadline = 0.0

    # ---------- 状态 ----------

    @property
    def cfg(self) -> dict:
        cfg = self.st.state.get("lock")
        if not isinstance(cfg, dict):
            cfg = _deep_fill(DEFAULT_LOCK, {})
            self.st.state["lock"] = cfg
        return cfg

    @property
    def state(self) -> str:
        return UNLOCKED if self.cfg.get("state") == UNLOCKED else LOCKED

    def is_locked(self) -> bool:
        return self.state == LOCKED

    def is_unlocked(self) -> bool:
        return self.state == UNLOCKED

    def remaining_seconds(self) -> int:
        if self.is_locked():
            return 0
        return max(0, int(round(self._deadline - self._clock())))

    def remaining_text(self) -> str:
        seconds = self.remaining_seconds()
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    # ---------- 动作 ----------

    def unlock(self, minutes: int, source: str = "") -> dict:
        minutes = int(minutes)
        if minutes <= 0:
            raise ValueError("解锁时长必须大于 0")
        seconds = minutes * 60
        self._deadline = self._clock() + seconds
        cfg = self.cfg
        cfg["state"] = UNLOCKED
        cfg["unlockedMinutes"] = minutes
        cfg["deadlineWall"] = int(time.time()) + seconds
        cfg["lastUnlockSource"] = str(source or "")
        cfg["lastSeenWall"] = int(time.time())
        self.st.save_state()
        return {"minutes": minutes, "seconds": seconds, "deadlineWall": cfg["deadlineWall"]}

    def unlock_until_tomorrow(self, source: str = "parent") -> dict:
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds = max(60, int((tomorrow - now).total_seconds()))
        self._deadline = self._clock() + seconds
        cfg = self.cfg
        cfg["state"] = UNLOCKED
        cfg["unlockedMinutes"] = round(seconds / 60)
        cfg["deadlineWall"] = int(time.time()) + seconds
        cfg["lastUnlockSource"] = str(source or "")
        cfg["lastSeenWall"] = int(time.time())
        self.st.save_state()
        return {"minutes": round(seconds / 60), "seconds": seconds, "deadlineWall": cfg["deadlineWall"]}

    def extend(self, minutes: int, source: str = "parent") -> dict:
        """在剩余时间上追加（家长加时用）。"""
        minutes = int(minutes)
        if minutes <= 0:
            raise ValueError("加时时长必须大于 0")
        extra = minutes * 60
        if self.is_unlocked():
            self._deadline += extra
            cfg = self.cfg
            cfg["deadlineWall"] = int(time.time()) + max(0, int(self._deadline - self._clock()))
            self.st.save_state()
            return {"minutes": minutes, "seconds": self.remaining_seconds()}
        return self.unlock(minutes, source)

    def force_lock(self, reason: str = REASON_MANUAL) -> bool:
        """强制回锁，返回是否真的发生了状态变化。"""
        if self.is_locked():
            return False
        cfg = self.cfg
        cfg["state"] = LOCKED
        cfg["deadlineWall"] = 0
        cfg["unlockedMinutes"] = 0
        cfg["lastLockReason"] = str(reason)
        cfg["lockCount"] = _safe_int(cfg.get("lockCount")) + 1
        cfg["lastSeenWall"] = int(time.time())
        self._deadline = 0.0
        self.st.save_state()
        return True

    def tick(self) -> str | None:
        """每秒调用一次。到点则回锁并返回回锁原因，否则返回 None。"""
        if not self.is_unlocked():
            return None
        if self._clock() < self._deadline:
            return None
        self.force_lock(REASON_TIMEUP)
        return REASON_TIMEUP

    # ---------- 心跳与异常 ----------

    def heartbeat(self) -> str | None:
        """每 10 秒落盘一次。检测到时钟回拨则立即回锁并返回 tamper。"""
        cfg = self.cfg
        now = int(time.time())
        last = _safe_int(cfg.get("lastSeenWall"))
        tamper = None
        if last and now < last - CLOCK_TOLERANCE:
            cfg["tamperCount"] = _safe_int(cfg.get("tamperCount")) + 1
            tamper = REASON_TAMPER
            self.force_lock(REASON_TAMPER)
        cfg["lastSeenWall"] = max(now, last)
        if self.is_unlocked():
            cfg["deadlineWall"] = now + max(0, int(round(self._deadline - self._clock())))
        self.st.save_state()
        return tamper

    def recover_from_crash(self) -> dict:
        """启动时调用：把上次留下的「已解锁」状态一律收回。"""
        cfg = self.cfg
        info = {"abnormal": False, "tamper": False, "wasUnlocked": False}
        if self.state == UNLOCKED:
            info["wasUnlocked"] = True
            cfg["abnormalExit"] = _safe_int(cfg.get("abnormalExit")) + 1
            info["abnormal"] = True
            self.force_lock(REASON_STARTUP)
        tamper = self.heartbeat()
        if tamper:
            info["tamper"] = True
        return info

    def stats(self) -> dict:
        cfg = self.cfg
        return {
            "state": self.state,
            "remainingSeconds": self.remaining_seconds(),
            "lockCount": _safe_int(cfg.get("lockCount")),
            "abnormalExit": _safe_int(cfg.get("abnormalExit")),
            "tamperCount": _safe_int(cfg.get("tamperCount")),
            "lastLockReason": cfg.get("lastLockReason") or "",
            "lastLockLabel": REASON_LABEL.get(str(cfg.get("lastLockReason") or ""), ""),
            "lastUnlockSource": cfg.get("lastUnlockSource") or "",
        }
