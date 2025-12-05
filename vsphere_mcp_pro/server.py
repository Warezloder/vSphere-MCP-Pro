from __future__ import annotations

import functools
import time
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .audit import AuditEvent, Auditor
from .authz import Authorizer, CallerContext, TokenBucketLimiter, set_caller
from .config import AppConfig, load_config
from .vsphere_client import VsphereClient


def _choose_host(cfg: AppConfig, hostname: Optional[str]) -> str:
    host = (hostname or cfg.vsphere.host).strip()
    if cfg.vsphere.allowed_hosts and host not in cfg.vsphere.allowed_hosts:
        raise PermissionError(f"Hostname '{host}' not in allowed set")
    return host


def _with_guard(tool_name: str, destructive: bool = False):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            cfg: AppConfig = kwargs.pop("_cfg")
            auditor: Auditor = kwargs.pop("_auditor")
            limiter: TokenBucketLimiter = kwargs.pop("_limiter")
            authz: Authorizer = kwargs.pop("_authz")

            token = kwargs.pop("token", None)
            confirm = kwargs.get("confirm", False)
            role = authz.resolve_role(token)
            set_caller(CallerContext(token=token, role=role))

            start = time.perf_counter()
            ok = False
            error = None
            host_used: Optional[str] = None

            try:
                key = token or "anonymous"
                if not limiter.allow(key):
                    raise PermissionError("Rate limit exceeded")

                if not authz.is_allowed(tool_name, role):
                    raise PermissionError(f"Tool '{tool_name}' not allowed for role '{role or 'none'}'")

                if destructive and not confirm:
                    raise PermissionError("Destructive operation: set confirm=True to proceed")

                result = fn(*args, **kwargs)
                ok = True
                if isinstance(result, dict) and "meta" in result and "host" in result["meta"]:
                    host_used = result["meta"]["host"]
                return result
            except Exception as e:
                error = str(e)
                raise
            finally:
                dur = (time.perf_counter() - start) * 1000.0
                auditor.log(AuditEvent(
                    ts=time.time(), tool=tool_name, ok=ok, duration_ms=dur, args=kwargs,
                    error=error, host=host_used, role=role
                ))
        return wrapper
    return deco


def build_server(cfg: AppConfig) -> FastMCP:
    mcp = FastMCP(cfg.server.name)
    auditor = Auditor(cfg.server.audit_log_path)
    authz = Authorizer(cfg.auth)
    limiter = TokenBucketLimiter(cfg.ratelimit)

    def inject(fn, name: str, destructive: bool = False):
        wrapped = _with_guard(name, destructive)(fn)
        mcp.tool(name=name)(functools.partial(wrapped, _cfg=cfg, _auditor=auditor, _limiter=limiter, _authz=authz))

    def client_for(hostname: Optional[str]) -> VsphereClient:
        host = _choose_host(cfg, hostname)
        local_cfg = cfg.model_copy(deep=True)
        local_cfg.vsphere.host = host
        c = VsphereClient(local_cfg.vsphere)
        c.login()
        return c

    @inject
    def list_vms(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        vms = c.list_vms()
        return {"ok": True, "meta": {"host": c._cfg.host}, "count": len(vms), "vms": vms}

    @inject
    def get_vm_details(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        vm = c.get_vm(vm_id)
        return {"ok": True, "meta": {"host": c._cfg.host}, "vm": vm}

    @inject
    def list_hosts(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.list_hosts()
        return {"ok": True, "meta": {"host": c._cfg.host}, "count": len(data), "hosts": data}

    @inject
    def list_datastores(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.list_datastores()
        return {"ok": True, "meta": {"host": c._cfg.host}, "count": len(data), "datastores": data}

    @inject
    def list_networks(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.list_networks()
        return {"ok": True, "meta": {"host": c._cfg.host}, "count": len(data), "networks": data}

    @inject
    def list_datacenters(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.list_datacenters()
        return {"ok": True, "meta": {"host": c._cfg.host}, "count": len(data), "datacenters": data}

    @inject
    def power_on_vm(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.power_start(vm_id)
        return {"ok": True, "meta": {"host": c._cfg.host}, "result": data}

    @inject
    def power_off_vm(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.power_stop(vm_id)
        return {"ok": True, "meta": {"host": c._cfg.host}, "result": data}

    @inject
    def restart_vm(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.power_reset(vm_id)
        return {"ok": True, "meta": {"host": c._cfg.host}, "result": data}

    @inject
    def list_vm_snapshots(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.list_snapshots(vm_id)
        return {"ok": True, "meta": {"host": c._cfg.host}, "count": (len(data) if isinstance(data, list) else None), "snapshots": data}

    @inject
    def create_vm_snapshot(vm_id: str, snapshot_name: str, description: str = "", memory: bool = False, quiesce: bool = False,
                           hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.create_snapshot(vm_id, snapshot_name, description=description, memory=memory, quiesce=quiesce)
        return {"ok": True, "meta": {"host": c._cfg.host}, "result": data}

    @inject
    def delete_vm_snapshot(vm_id: str, snapshot_id: str, confirm: bool = False,
                           hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.delete_snapshot(vm_id, snapshot_id)
        return {"ok": True, "meta": {"host": c._cfg.host}, "result": data}

    @inject
    def delete_vm(vm_id: str, confirm: bool = False, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        data = c.delete_vm(vm_id)
        return {"ok": True, "meta": {"host": c._cfg.host}, "result": data}

    @inject
    def modify_vm_resources(vm_id: str, cpu_count: Optional[int] = None, memory_gb: Optional[int] = None,
                            confirm: bool = False, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        if cpu_count is None and memory_gb is None:
            raise ValueError("cpu_count or memory_gb required")
        c = client_for(hostname)
        res = {}
        if cpu_count is not None:
            res["cpu"] = c.set_cpu(vm_id, cpu_count)
        if memory_gb is not None:
            res["memory"] = c.set_memory(vm_id, int(memory_gb * 1024))
        return {"ok": True, "meta": {"host": c._cfg.host}, "result": res}

    @inject
    def get_datastore_usage(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        dss = c.list_datastores()
        return {"ok": True, "meta": {"host": c._cfg.host}, "count": len(dss), "datastores": dss}

    @inject
    def get_resource_utilization_summary(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None) -> Dict[str, Any]:
        c = client_for(hostname)
        return {"ok": True, "meta": {"host": c._cfg.host}, "summary": {
            "vms": len(c.list_vms()),
            "hosts": len(c.list_hosts()),
            "datastores": len(c.list_datastores()),
            "networks": len(c.list_networks()),
            "datacenters": len(c.list_datacenters()),
        }}

    return mcp


def main() -> None:
    load_dotenv()
    cfg = load_config()
    mcp = build_server(cfg)
    mcp.run(host=cfg.server.host, port=cfg.server.port, path=cfg.server.mcp_path)


if __name__ == "__main__":
    main()
