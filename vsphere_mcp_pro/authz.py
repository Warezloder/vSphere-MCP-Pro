from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from .config import AuthConfig, RateLimitConfig

_thread_ctx = threading.local()


@dataclass
class CallerContext:
    token: Optional[str]
    role: Optional[str]
    remote: Optional[str] = None


def set_caller(ctx: CallerContext) -> None:
    _thread_ctx.caller = ctx


def get_caller() -> CallerContext:
    return getattr(_thread_ctx, "caller", CallerContext(token=None, role=None))


class Authorizer:
    def __init__(self, auth: AuthConfig):
        self._tokens = auth.tokens_to_roles
        self._roles = auth.roles_to_tools
        self._enforce = auth.enforce

    def resolve_role(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        return self._tokens.get(token)

    def is_allowed(self, tool_name: str, role: Optional[str]) -> bool:
        if not self._enforce:
            return True
        if not role:
            return False
        return tool_name in self._roles.get(role, set())


class TokenBucketLimiter:
    def __init__(self, cfg: RateLimitConfig):
        self.enabled = cfg.enabled
        self.rate = cfg.rate_per_sec
        self.burst = cfg.burst
        self._buckets: Dict[str, Dict[str, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if not self.enabled:
            return True
        now = time.monotonic()
        with self._lock:
            b = self._buckets.setdefault(key, {"tokens": float(self.burst), "ts": now})
            elapsed = now - b["ts"]
            b["tokens"] = min(self.burst, b["tokens"] + elapsed * self.rate)
            b["ts"] = now
            if b["tokens"] >= 1.0:
                b["tokens"] -= 1.0
                return True
            return False
