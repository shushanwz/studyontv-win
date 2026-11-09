"""家长控制：密码、恢复码、解锁档位与加固配置。

设计要点：
  * 密码只存 PBKDF2-HMAC-SHA256 的派生值，不存明文、不可逆推；
  * 恢复码一次性使用，用于忘记密码时重设；
  * 错误次数落盘，重启不清零——否则重启一次就白给一次尝试机会；
  * 加固开关只读写配置，真正的系统调用在 quizwin/platform/winlock.py。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Any

from .storage import DEFAULT_PARENT, _deep_fill, _safe_int

ALGO = "pbkdf2_sha256"
ITERATIONS = 260_000
SALT_BYTES = 16
PASSWORD_MIN = 6
PASSWORD_MAX = 64
MAX_FAILS = 5
COOLDOWNS = (60, 120, 300, 900)
TIER_MIN = 1
TIER_MAX = 60
TIER_COUNT_MAX = 6

# 去掉 I O 0 1，避免抄写时看错
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# ---------------------------------------------------------------- 哈希


def _derive(secret: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, int(iterations)).hex()


def make_password_record(password: str, iterations: int = ITERATIONS) -> dict[str, Any]:
    salt = os.urandom(SALT_BYTES)
    return {
        "algo": ALGO,
        "iters": int(iterations),
        "salt": salt.hex(),
        "hash": _derive(password, salt, iterations),
    }


def verify_password_record(password: str, record: dict | None) -> bool:
    if not isinstance(record, dict):
        return False
    try:
        salt = bytes.fromhex(str(record.get("salt") or ""))
        iterations = _safe_int(record.get("iters"), ITERATIONS)
        expected = str(record.get("hash") or "")
    except (TypeError, ValueError):
        return False
    if not salt or not expected:
        return False
    return hmac.compare_digest(_derive(password, salt, iterations), expected)


def validate_password(password: str) -> str | None:
    """返回错误文案，通过则返回 None。"""
    text = str(password or "")
    if len(text) < PASSWORD_MIN:
        return f"密码至少 {PASSWORD_MIN} 位"
    if len(text) > PASSWORD_MAX:
        return f"密码最多 {PASSWORD_MAX} 位"
    if text.strip() != text:
        return "密码开头和结尾不能是空格"
    if len(set(text)) == 1:
        return "密码不能全部是同一个字符"
    return None


def generate_recovery_code() -> str:
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(code: str) -> str:
    keep = [ch.upper() for ch in str(code or "") if ch.isalnum()]
    return "".join(keep)


# ---------------------------------------------------------------- 控制器


class ParentControl:
    def __init__(self, storage):
        self.st = storage

    # ---------- 基础字段 ----------

    @property
    def cfg(self) -> dict:
        cfg = self.st.state.get("parent")
        if not isinstance(cfg, dict):
            cfg = _deep_fill(DEFAULT_PARENT, {})
            self.st.state["parent"] = cfg
        return cfg

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def set_enabled(self, value: bool) -> None:
        self.cfg["enabled"] = bool(value)
        self.st.save_state()

    @property
    def has_password(self) -> bool:
        return bool(self.cfg.get("password"))

    @property
    def setup_done(self) -> bool:
        return bool(self.cfg.get("setupDone")) and self.has_password

    def mark_setup_done(self) -> None:
        self.cfg["setupDone"] = True
        self.st.save_state()

    # ---------- 密码 ----------

    def set_password(self, password: str) -> tuple[bool, str, str]:
        """设置（或重设）密码，返回 (成功, 提示, 新恢复码)。"""
        error = validate_password(password)
        if error:
            return False, error, ""
        code = generate_recovery_code()
        self.cfg["password"] = make_password_record(password)
        self.cfg["recovery"] = {
            "hash": _derive(normalize_code(code), b"recovery:" + bytes.fromhex(self.cfg["password"]["salt"]), ITERATIONS),
            "iters": ITERATIONS,
            "used": False,
        }
        self.cfg["failCount"] = 0
        self.cfg["lockUntil"] = 0
        self.cfg["setupDone"] = True
        self.st.save_state()
        return True, "密码已保存", code

    def check(self, password: str) -> tuple[bool, str]:
        """校验密码，返回 (通过, 状态)。状态：ok / wrong / cooldown / nopass。"""
        cfg = self.cfg
        if not self.has_password:
            return False, "nopass"
        now = int(time.time())
        until = _safe_int(cfg.get("lockUntil"))
        if until > now:
            return False, "cooldown"
        if verify_password_record(password, cfg.get("password")):
            if _safe_int(cfg.get("failCount")) or until:
                cfg["failCount"] = 0
                cfg["lockUntil"] = 0
                self.st.save_state()
            return True, "ok"
        self._register_failure(now)
        return False, "wrong"

    def _register_failure(self, now: int) -> None:
        cfg = self.cfg
        fails = _safe_int(cfg.get("failCount")) + 1
        cfg["failCount"] = fails
        if fails % MAX_FAILS == 0:
            level = min(fails // MAX_FAILS - 1, len(COOLDOWNS) - 1)
            cfg["lockUntil"] = now + COOLDOWNS[level]
        self.st.save_state()

    def lockout_seconds(self) -> int:
        return max(0, int(self.cfg.get("lockUntil") or 0) - int(time.time()))

    def fails_left(self) -> int:
        fails = int(self.cfg.get("failCount") or 0)
        return max(0, MAX_FAILS - (fails % MAX_FAILS)) if fails % MAX_FAILS else MAX_FAILS

    # ---------- 恢复码 ----------

    def verify_recovery(self, code: str) -> bool:
        rec = self.cfg.get("recovery") or {}
        if rec.get("used"):
            return False
        expect = str(rec.get("hash") or "")
        if not expect:
            return False
        salt = b"recovery:" + bytes.fromhex(str((self.cfg.get("password") or {}).get("salt") or ""))
        got = _derive(normalize_code(code), salt, _safe_int(rec.get("iters"), ITERATIONS))
        return hmac.compare_digest(got, expect)

    def reset_with_recovery(self, code: str, new_password: str) -> tuple[bool, str, str]:
        """用恢复码重设密码，成功后恢复码作废并换新。"""
        rec = self.cfg.get("recovery") or {}
        if rec.get("used"):
            return False, "这个恢复码已经用过了", ""
        if not self.verify_recovery(code):
            # 恢复码错误同样计入失败次数，堵住暴力试码
            self._register_failure(int(time.time()))
            return False, "恢复码不正确", ""
        ok, message, fresh = self.set_password(new_password)
        if not ok:
            return False, message, ""
        return True, "密码已重设，这是新的恢复码", fresh

    def regenerate_recovery(self) -> tuple[bool, str]:
        """家长主动换一张恢复码，旧码立即作废。"""
        if not self.has_password:
            return False, ""
        code = generate_recovery_code()
        salt = bytes.fromhex(str((self.cfg.get("password") or {}).get("salt") or ""))
        self.cfg["recovery"] = {
            "hash": _derive(normalize_code(code), b"recovery:" + salt, ITERATIONS),
            "iters": ITERATIONS,
            "used": False,
        }
        self.st.save_state()
        return True, code

    # ---------- 档位 ----------

    @property
    def tiers(self) -> list[int]:
        raw = self.cfg.get("tiers") or [10, 15, 20, 25]
        tiers = sorted({int(v) for v in raw if isinstance(v, (int, float)) and TIER_MIN <= int(v) <= TIER_MAX})
        return tiers[:TIER_COUNT_MAX] or [10]

    def set_tiers(self, tiers: list[int]) -> tuple[bool, str]:
        clean = sorted({int(v) for v in tiers if isinstance(v, (int, float))})
        if not clean:
            return False, "至少要保留一个档位"
        if len(clean) > TIER_COUNT_MAX:
            return False, f"最多 {TIER_COUNT_MAX} 个档位"
        if clean[0] < TIER_MIN or clean[-1] > TIER_MAX:
            return False, f"档位范围是 {TIER_MIN}–{TIER_MAX} 分钟"
        self.cfg["tiers"] = clean
        self.st.save_state()
        return True, "档位已保存"

    # ---------- 加固与设置门 ----------

    def hardening(self, key: str) -> bool:
        return bool((self.cfg.get("hardening") or {}).get(key, False))

    def set_hardening(self, key: str, value: bool) -> None:
        self.cfg.setdefault("hardening", {})[key] = bool(value)
        self.st.save_state()

    @property
    def banks_require_password(self) -> bool:
        return bool(self.cfg.get("banksRequirePassword", True))

    @property
    def settings_grace_seconds(self) -> int:
        return max(0, _safe_int(self.cfg.get("settingsGraceSeconds")))

    def overlay_position(self) -> tuple[int, int] | None:
        pos = self.cfg.get("overlay") or {}
        x, y = _safe_int(pos.get("x"), -1), _safe_int(pos.get("y"), -1)
        return None if x < 0 or y < 0 else (x, y)

    def save_overlay_position(self, x: int, y: int) -> None:
        self.cfg["overlay"] = {"x": int(x), "y": int(y)}
        self.st.save_state()
