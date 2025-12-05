from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from .authz import get_caller


@dataclass
class AuditEvent:
    ts: float
    tool: str
    ok: bool
    duration_ms: float
    args: Dict[str, Any]
    error: Optional[str] = None
    host: Optional[str] = None
    role: Optional[str] = None


class Auditor:
    def __init__(self, path: Optional[str] = None):
        self._sink = open(path, "a", buffering=1) if path else sys.stdout

    def log(self, event: AuditEvent) -> None:
        data = asdict(event)
        for k in list(data.get("args", {}).keys()):
            if "password" in k.lower() or "token" in k.lower():
                data["args"][k] = "***"
        self._sink.write(json.dumps(data) + "\n")
