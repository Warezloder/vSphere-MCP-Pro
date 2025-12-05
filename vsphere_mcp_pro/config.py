from __future__ import annotations

import json
import os
from typing import Dict, Optional, Set

from pydantic import BaseModel, Field, field_validator


class AuthConfig(BaseModel):
    tokens_to_roles: Dict[str, str] = Field(default_factory=dict)
    roles_to_tools: Dict[str, Set[str]] = Field(default_factory=dict)
    enforce: bool = True

    @field_validator("roles_to_tools", mode="before")
    @classmethod
    def coerce_sets(cls, v):
        return {k: set(vv) for k, vv in (v or {}).items()}


class RateLimitConfig(BaseModel):
    enabled: bool = True
    rate_per_sec: float = 5.0
    burst: int = 10


class VsphereConfig(BaseModel):
    host: str
    user: str
    password: str
    api_mode: str = Field(default="api")  # "api" | "rest"
    verify_ssl: bool = True
    ca_bundle: Optional[str] = None
    default_timeout_s: float = 20.0
    request_retries: int = 3
    backoff_factor: float = 0.5
    allowed_hosts: Set[str] = Field(default_factory=set)


class ServerConfig(BaseModel):
    name: str = "vsphere-mcp-pro"
    host: str = "0.0.0.0"
    port: int = 8000
    mcp_path: str = "/mcp"
    audit_log_path: Optional[str] = None
    verbose_default: bool = False


class AppConfig(BaseModel):
    vsphere: VsphereConfig
    auth: AuthConfig
    ratelimit: RateLimitConfig
    server: ServerConfig


def _env_json(name: str):
    v = os.getenv(name)
    if not v:
        return None
    return json.loads(v)


def load_config() -> AppConfig:
    allowed_hosts = set()
    if os.getenv("ALLOWED_VCENTER_HOSTS"):
        allowed_hosts = {h.strip() for h in os.getenv("ALLOWED_VCENTER_HOSTS", "").split(",") if h.strip()}

    roles_to_tools = _env_json("ROLES_TO_TOOLS") or {
        "read": {
            "list_vms", "get_vm_details", "list_hosts", "list_datastores",
            "list_networks", "list_datacenters", "get_datastore_usage",
            "get_resource_utilization_summary", "list_vm_snapshots",
        },
        "ops": {
            "power_on_vm", "power_off_vm", "restart_vm", "create_vm_snapshot",
            "delete_vm_snapshot", "list_vm_snapshots",
        },
        "admin": {
            "delete_vm", "modify_vm_resources",
        },
    }

    tokens_to_roles = _env_json("TOKENS_TO_ROLES") or {}

    cfg = AppConfig(
        vsphere=VsphereConfig(
            host=os.getenv("VCENTER_HOST", "").strip() or "CHANGE_ME",
            user=os.getenv("VCENTER_USER", ""),
            password=os.getenv("VCENTER_PASSWORD", ""),
            api_mode=os.getenv("VSPHERE_API_MODE", "api").lower(),
            verify_ssl=os.getenv("INSECURE", "false").lower() not in {"1", "true", "yes"},
            ca_bundle=os.getenv("VCENTER_CA_BUNDLE"),
            default_timeout_s=float(os.getenv("VCENTER_TIMEOUT_S", "20")),
            request_retries=int(os.getenv("VCENTER_RETRIES", "3")),
            backoff_factor=float(os.getenv("VCENTER_BACKOFF", "0.5")),
            allowed_hosts=allowed_hosts or {os.getenv("VCENTER_HOST", "").strip()} - {""},
        ),
        auth=AuthConfig(
            tokens_to_roles=tokens_to_roles,
            roles_to_tools=roles_to_tools,
            enforce=os.getenv("AUTH_ENFORCE", "true").lower() in {"1", "true", "yes"},
        ),
        ratelimit=RateLimitConfig(
            enabled=os.getenv("RATE_LIMIT", "true").lower() in {"1", "true", "yes"},
            rate_per_sec=float(os.getenv("RATE_LIMIT_RPS", "5")),
            burst=int(os.getenv("RATE_LIMIT_BURST", "10")),
        ),
        server=ServerConfig(
            name=os.getenv("SERVER_NAME", "vsphere-mcp-pro"),
            host=os.getenv("SERVER_HOST", "0.0.0.0"),
            port=int(os.getenv("SERVER_PORT", "8000")),
            mcp_path=os.getenv("MCP_PATH", "/mcp"),
            audit_log_path=os.getenv("AUDIT_LOG_PATH"),
            verbose_default=os.getenv("VERBOSE_DEFAULT", "false").lower() in {"1", "true", "yes"},
        ),
    )
    if cfg.vsphere.host == "CHANGE_ME":
        raise RuntimeError("Set VCENTER_HOST/VCENTER_USER/VCENTER_PASSWORD")
    return cfg
