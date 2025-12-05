from __future__ import annotations

from typing import Any, Dict, Optional
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import VsphereConfig


class VsphereClient:
    def __init__(self, cfg: VsphereConfig):
        self._cfg = cfg
        self._session = requests.Session()
        retry = Retry(
            total=cfg.request_retries,
            backoff_factor=cfg.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods={"HEAD", "GET", "POST", "PUT", "PATCH", "DELETE"},
            raise_on_status=False,
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session.verify = cfg.ca_bundle or cfg.verify_ssl
        self._timeout = cfg.default_timeout_s
        self._lock = threading.Lock()
        self._session_id: Optional[str] = None
        self._base = f"https://{cfg.host}"
        self._api_mode = "api" if cfg.api_mode == "api" else "rest"

    def _auth_header(self) -> Dict[str, str]:
        return {"vmware-api-session-id": self._session_id} if self._session_id else {}

    def login(self) -> None:
        with self._lock:
            if self._session_id:
                return
            # Try /api
            if self._api_mode == "api":
                url = f"{self._base}/api/session"
                r = self._session.post(url, timeout=self._timeout, auth=(self._cfg.user, self._cfg.password))
                if r.ok:
                    token = None
                    try:
                        token = r.json()
                        if isinstance(token, dict) and "value" in token:
                            token = token["value"]
                        elif isinstance(token, (list, dict)):
                            token = None
                    except Exception:
                        token = r.text.strip() or None
                    if not token:
                        token = r.headers.get("vmware-api-session-id") or r.cookies.get("vmware-api-session-id")
                    if not token:
                        raise RuntimeError("vCenter /api/session returned no token")
                    self._session_id = token
                    return
            # Fallback to /rest
            url = f"{self._base}/rest/com/vmware/cis/session"
            r = self._session.post(url, timeout=self._timeout, auth=(self._cfg.user, self._cfg.password))
            if not r.ok:
                raise RuntimeError(f"login failed: HTTP {r.status_code} {r.text[:200]}")
            token = r.json().get("value")
            if not token:
                raise RuntimeError("vCenter /rest/com/vmware/cis/session returned no token")
            self._session_id = token

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                 json_body: Optional[Any] = None) -> requests.Response:
        url = f"{self._base}{path}"
        headers = self._auth_header()
        r = self._session.request(method, url, headers=headers, params=params, json=json_body, timeout=self._timeout)
        if r.status_code == 401:
            with self._lock:
                self._session_id = None
            self.login()
            headers = self._auth_header()
            r = self._session.request(method, url, headers=headers, params=params, json=json_body, timeout=self._timeout)
        return r

    def _v(self, rest: str, api: str) -> str:
        return api if self._api_mode == "api" else rest

    def list_vms(self) -> Any:
        path = self._v("/rest/vcenter/vm", "/api/vcenter/vm")
        r = self._request("GET", path)
        return r.json().get("value") if self._api_mode == "rest" else r.json()

    def get_vm(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}", f"/api/vcenter/vm/{vm}")
        r = self._request("GET", path)
        return r.json().get("value") if self._api_mode == "rest" else r.json()

    def power_start(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/power/start", f"/api/vcenter/vm/{vm}/power/start")
        r = self._request("POST", path)
        return r.json() if r.headers.get("content-type","").startswith("application/json") else {}

    def power_stop(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/power/stop", f"/api/vcenter/vm/{vm}/power/stop")
        r = self._request("POST", path)
        return r.json() if r.headers.get("content-type","").startswith("application/json") else {}

    def power_reset(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/power/reset", f"/api/vcenter/vm/{vm}/power/reset")
        r = self._request("POST", path)
        return r.json() if r.headers.get("content-type","").startswith("application/json") else {}

    def delete_vm(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}", f"/api/vcenter/vm/{vm}")
        r = self._request("DELETE", path)
        return {} if r.status_code in (200, 204) else r.json()

    def list_hosts(self) -> Any:
        path = self._v("/rest/vcenter/host", "/api/vcenter/host")
        r = self._request("GET", path)
        return r.json().get("value") if self._api_mode == "rest" else r.json()

    def list_datastores(self) -> Any:
        path = self._v("/rest/vcenter/datastore", "/api/vcenter/datastore")
        r = self._request("GET", path)
        return r.json().get("value") if self._api_mode == "rest" else r.json()

    def list_networks(self) -> Any:
        path = self._v("/rest/vcenter/network", "/api/vcenter/network")
        r = self._request("GET", path)
        return r.json().get("value") if self._api_mode == "rest" else r.json()

    def list_datacenters(self) -> Any:
        path = self._v("/rest/vcenter/datacenter", "/api/vcenter/datacenter")
        r = self._request("GET", path)
        return r.json().get("value") if self._api_mode == "rest" else r.json()

    def list_snapshots(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/snapshot", f"/api/vcenter/vm/{vm}/snapshot")
        r = self._request("GET", path)
        return r.json().get("value") if self._api_mode == "rest" else r.json()

    def create_snapshot(self, vm: str, name: str, description: str = "", memory: bool = False, quiesce: bool = False) -> Any:
        body = {"spec": {"description": description, "memory": memory, "name": name, "quiesce": quiesce}} if self._api_mode == "rest" else {
            "description": description, "memory": memory, "name": name, "quiesce": quiesce
        }
        path = self._v(f"/rest/vcenter/vm/{vm}/snapshot", f"/api/vcenter/vm/{vm}/snapshot")
        r = self._request("POST", path, json_body=body)
        return r.json().get("value") if self._api_mode == "rest" else r.json()

    def delete_snapshot(self, vm: str, snapshot: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/snapshot/{snapshot}", f"/api/vcenter/vm/{vm}/snapshot/{snapshot}")
        r = self._request("DELETE", path)
        return {} if r.status_code in (200, 204) else r.json()

    def set_cpu(self, vm: str, count: int) -> Any:
        body = {"spec": {"count": count}} if self._api_mode == "rest" else {"count": count}
        path = self._v(f"/rest/vcenter/vm/{vm}/hardware/cpu", f"/api/vcenter/vm/{vm}/hardware/cpu")
        r = self._request("PATCH", path, json_body=body)
        return r.json() if r.headers.get("content-type","").startswith("application/json") else {}

    def set_memory(self, vm: str, memory_mib: int) -> Any:
        body = {"spec": {"size_MiB": memory_mib}} if self._api_mode == "rest" else {"size_MiB": memory_mib}
        path = self._v(f"/rest/vcenter/vm/{vm}/hardware/memory", f"/api/vcenter/vm/{vm}/hardware/memory")
        r = self._request("PATCH", path, json_body=body)
        return r.json() if r.headers.get("content-type","").startswith("application/json") else {}
