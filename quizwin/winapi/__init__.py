"""Windows 系统层：输入封锁与进程守护。

只依赖 ctypes 与标准库，不改系统设置、不装驱动。
"""

from .harden import (
    HardenOptions,
    Hardening,
    block_reason,
    set_task_manager_disabled,
    task_manager_is_disabled,
)
from .watchdog import Watchdog

__all__ = [
    "HardenOptions",
    "Hardening",
    "Watchdog",
    "block_reason",
    "set_task_manager_disabled",
    "task_manager_is_disabled",
]
