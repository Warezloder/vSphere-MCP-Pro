from __future__ import annotations

import functools
import time
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .audit import AuditEvent, Auditor
from .authz import Authorizer, CallerContext, TokenBucketLimiter, set_caller
from .config import AppConfig, load_config
from .vsphere_client import VsphereClientPool


def _with_guard(tool_name: str, destructive: bool = False):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            cfg: AppConfig = kwargs.pop("_cfg")
            auditor: Auditor = kwargs.pop("_auditor")
            limiter: TokenBucketLimiter = kwargs.pop("_limiter")
            authz: Authorizer = kwargs.pop("_authz")
            pool: VsphereClientPool = kwargs.pop("_pool")

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

                result = fn(*args, _pool=pool, **kwargs)
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
    pool = VsphereClientPool(cfg)

    def inject(name: str, destructive: bool = False):
        """Decorator factory that wraps a tool with auth, rate limiting, and auditing."""
        def decorator(fn):
            wrapped = _with_guard(name, destructive)(fn)
            bound = functools.partial(
                wrapped,
                _cfg=cfg,
                _auditor=auditor,
                _limiter=limiter,
                _authz=authz,
                _pool=pool,
            )
            mcp.tool(name=name)(bound)
            return fn
        return decorator

    # --- VM Discovery ---

    @inject("list_vms")
    def list_vms(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                 *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        vms = c.list_vms()
        return {"ok": True, "meta": {"host": c.host}, "count": len(vms), "vms": vms}

    @inject("get_vm_details")
    def get_vm_details(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                       *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        vm = c.get_vm(vm_id)
        return {"ok": True, "meta": {"host": c.host}, "vm": vm}

    # --- Inventory Discovery ---

    @inject("list_hosts")
    def list_hosts(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                   *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.list_hosts()
        return {"ok": True, "meta": {"host": c.host}, "count": len(data), "hosts": data}

    @inject("list_datastores")
    def list_datastores(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                        *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.list_datastores()
        return {"ok": True, "meta": {"host": c.host}, "count": len(data), "datastores": data}

    @inject("list_networks")
    def list_networks(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                      *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.list_networks()
        return {"ok": True, "meta": {"host": c.host}, "count": len(data), "networks": data}

    @inject("list_datacenters")
    def list_datacenters(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                         *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.list_datacenters()
        return {"ok": True, "meta": {"host": c.host}, "count": len(data), "datacenters": data}

    @inject("get_datastore_usage")
    def get_datastore_usage(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                            *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        dss = c.list_datastores()
        return {"ok": True, "meta": {"host": c.host}, "count": len(dss), "datastores": dss}

    @inject("get_resource_utilization_summary")
    def get_resource_utilization_summary(hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                                         *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        return {"ok": True, "meta": {"host": c.host}, "summary": {
            "vms": len(c.list_vms()),
            "hosts": len(c.list_hosts()),
            "datastores": len(c.list_datastores()),
            "networks": len(c.list_networks()),
            "datacenters": len(c.list_datacenters()),
        }}

    # --- Power Operations ---

    @inject("power_on_vm")
    def power_on_vm(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                    *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.power_start(vm_id)
        return {"ok": True, "meta": {"host": c.host}, "result": data}

    @inject("power_off_vm")
    def power_off_vm(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                     *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.power_stop(vm_id)
        return {"ok": True, "meta": {"host": c.host}, "result": data}

    @inject("restart_vm")
    def restart_vm(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                   *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.power_reset(vm_id)
        return {"ok": True, "meta": {"host": c.host}, "result": data}

    # --- Snapshot Operations ---

    @inject("list_vm_snapshots")
    def list_vm_snapshots(vm_id: str, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                          *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.list_snapshots(vm_id)
        return {"ok": True, "meta": {"host": c.host}, "count": (len(data) if isinstance(data, list) else None), "snapshots": data}

    @inject("create_vm_snapshot")
    def create_vm_snapshot(vm_id: str, snapshot_name: str, description: str = "", memory: bool = False, quiesce: bool = False,
                           hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                           *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.create_snapshot(vm_id, snapshot_name, description=description, memory=memory, quiesce=quiesce)
        return {"ok": True, "meta": {"host": c.host}, "result": data}

    @inject("delete_vm_snapshot", destructive=True)
    def delete_vm_snapshot(vm_id: str, snapshot_id: str, confirm: bool = False,
                           hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                           *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.delete_snapshot(vm_id, snapshot_id)
        return {"ok": True, "meta": {"host": c.host}, "result": data}

    # --- Destructive Operations (require confirm=True) ---

    @inject("delete_vm", destructive=True)
    def delete_vm(vm_id: str, confirm: bool = False, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                  *, _pool: VsphereClientPool) -> Dict[str, Any]:
        c = _pool.get(hostname)
        data = c.delete_vm(vm_id)
        return {"ok": True, "meta": {"host": c.host}, "result": data}

    @inject("modify_vm_resources", destructive=True)
    def modify_vm_resources(vm_id: str, cpu_count: Optional[int] = None, memory_gb: Optional[int] = None,
                            confirm: bool = False, hostname: Optional[str] = None, verbose: bool = False, token: Optional[str] = None,
                            *, _pool: VsphereClientPool) -> Dict[str, Any]:
        if cpu_count is None and memory_gb is None:
            raise ValueError("cpu_count or memory_gb required")
        c = _pool.get(hostname)
        res = {}
        if cpu_count is not None:
            res["cpu"] = c.set_cpu(vm_id, cpu_count)
        if memory_gb is not None:
            res["memory"] = c.set_memory(vm_id, int(memory_gb * 1024))
        return {"ok": True, "meta": {"host": c.host}, "result": res}

    return mcp


def main() -> None:
    load_dotenv()
    cfg = load_config()
    mcp = build_server(cfg)
    mcp.run(host=cfg.server.host, port=cfg.server.port, path=cfg.server.mcp_path)


if __name__ == "__main__":
    main()
