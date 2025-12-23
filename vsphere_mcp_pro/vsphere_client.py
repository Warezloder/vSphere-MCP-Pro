from __future__ import annotations

import atexit
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import AppConfig, VsphereConfig

logger = logging.getLogger(__name__)


class VsphereApiError(Exception):
    """Exception raised when vCenter API returns an error response."""

    def __init__(
        self,
        message: str,
        status_code: int,
        response_body: Optional[Dict[str, Any]] = None,
        path: Optional[str] = None,
    ):
        self.status_code = status_code
        self.response_body = response_body or {}
        self.path = path
        
        # Extract vCenter error details if available
        self.error_type = self._extract_error_type()
        self.error_messages = self._extract_error_messages()
        
        # Build detailed message
        detail = f"HTTP {status_code}"
        if path:
            detail += f" on {path}"
        if self.error_type:
            detail += f" [{self.error_type}]"
        if self.error_messages:
            detail += f": {'; '.join(self.error_messages)}"
        
        full_message = f"{message}: {detail}"
        super().__init__(full_message)

    def _extract_error_type(self) -> Optional[str]:
        """Extract error type from vCenter response."""
        # /api style: {"error_type": "NOT_FOUND", ...}
        if "error_type" in self.response_body:
            return self.response_body["error_type"]
        # /rest style: {"type": "com.vmware.vapi.std.errors.not_found", ...}
        if "type" in self.response_body:
            return self.response_body["type"].split(".")[-1].upper()
        # Nested value style
        if "value" in self.response_body and isinstance(self.response_body["value"], dict):
            return self.response_body["value"].get("error_type")
        return None

    def _extract_error_messages(self) -> List[str]:
        """Extract human-readable error messages from vCenter response."""
        messages = []
        
        # /api style: {"messages": [{"default_message": "..."}]}
        if "messages" in self.response_body:
            for msg in self.response_body.get("messages", []):
                if isinstance(msg, dict) and "default_message" in msg:
                    messages.append(msg["default_message"])
                elif isinstance(msg, str):
                    messages.append(msg)
        
        # /rest style: {"value": {"messages": [...]}}
        if "value" in self.response_body and isinstance(self.response_body["value"], dict):
            for msg in self.response_body["value"].get("messages", []):
                if isinstance(msg, dict) and "default_message" in msg:
                    messages.append(msg["default_message"])
        
        # Simple message field
        if "message" in self.response_body:
            messages.append(self.response_body["message"])
        
        return messages

    @property
    def is_not_found(self) -> bool:
        return self.status_code == 404 or (self.error_type and "NOT_FOUND" in self.error_type.upper())

    @property
    def is_unauthorized(self) -> bool:
        return self.status_code == 401

    @property
    def is_forbidden(self) -> bool:
        return self.status_code == 403

    @property
    def is_conflict(self) -> bool:
        return self.status_code == 409


class VsphereClient:
    """Thread-safe vCenter REST API client with session management."""

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
        self._last_used: float = 0.0

    @property
    def host(self) -> str:
        return self._cfg.host

    @property
    def is_authenticated(self) -> bool:
        return self._session_id is not None

    def _auth_header(self) -> Dict[str, str]:
        return {"vmware-api-session-id": self._session_id} if self._session_id else {}

    def login(self) -> None:
        with self._lock:
            if self._session_id:
                return
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
                    self._last_used = time.monotonic()
                    logger.debug("Logged in to %s via /api/session", self._cfg.host)
                    return
                else:
                    # /api login failed, try /rest
                    logger.debug("/api/session failed with %d, trying /rest", r.status_code)
            
            # Fallback to /rest
            url = f"{self._base}/rest/com/vmware/cis/session"
            r = self._session.post(url, timeout=self._timeout, auth=(self._cfg.user, self._cfg.password))
            if not r.ok:
                raise VsphereApiError(
                    "Login failed",
                    status_code=r.status_code,
                    response_body=self._safe_json(r),
                    path=url,
                )
            token = r.json().get("value")
            if not token:
                raise RuntimeError("vCenter /rest/com/vmware/cis/session returned no token")
            self._session_id = token
            self._last_used = time.monotonic()
            logger.debug("Logged in to %s via /rest/com/vmware/cis/session", self._cfg.host)

    def logout(self) -> None:
        """Terminate the vCenter session."""
        with self._lock:
            if not self._session_id:
                return
            try:
                if self._api_mode == "api":
                    url = f"{self._base}/api/session"
                else:
                    url = f"{self._base}/rest/com/vmware/cis/session"
                self._session.delete(url, headers=self._auth_header(), timeout=self._timeout)
                logger.debug("Logged out from %s", self._cfg.host)
            except Exception as e:
                logger.warning("Logout failed for %s: %s", self._cfg.host, e)
            finally:
                self._session_id = None

    def close(self) -> None:
        """Logout and close the underlying HTTP session."""
        self.logout()
        self._session.close()

    def touch(self) -> None:
        """Update last-used timestamp."""
        self._last_used = time.monotonic()

    @staticmethod
    def _safe_json(r: requests.Response) -> Optional[Dict[str, Any]]:
        """Safely parse JSON response, returning None on failure."""
        try:
            if r.headers.get("content-type", "").startswith("application/json"):
                return r.json()
        except Exception:
            pass
        return None

    def _check_response(
        self,
        r: requests.Response,
        path: str,
        operation: str,
        allow_statuses: Optional[List[int]] = None,
    ) -> None:
        """
        Validate response and raise VsphereApiError on failure.
        
        Args:
            r: The requests Response object
            path: API path for error context
            operation: Human-readable operation name (e.g., "list VMs")
            allow_statuses: Additional status codes to treat as success (beyond 2xx)
        """
        allow_statuses = allow_statuses or []
        
        if r.ok or r.status_code in allow_statuses:
            return
        
        raise VsphereApiError(
            f"Failed to {operation}",
            status_code=r.status_code,
            response_body=self._safe_json(r),
            path=path,
        )

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                 json_body: Optional[Any] = None) -> requests.Response:
        self.touch()
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

    def _extract_value(self, r: requests.Response) -> Any:
        """Extract value from response, handling /api vs /rest format differences."""
        data = r.json()
        if self._api_mode == "rest" and isinstance(data, dict) and "value" in data:
            return data["value"]
        return data

    # --- VM Operations ---

    def list_vms(self) -> Any:
        path = self._v("/rest/vcenter/vm", "/api/vcenter/vm")
        r = self._request("GET", path)
        self._check_response(r, path, "list VMs")
        return self._extract_value(r)

    def get_vm(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}", f"/api/vcenter/vm/{vm}")
        r = self._request("GET", path)
        self._check_response(r, path, f"get VM '{vm}'")
        return self._extract_value(r)

    def power_start(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/power/start", f"/api/vcenter/vm/{vm}/power/start")
        r = self._request("POST", path)
        self._check_response(r, path, f"power on VM '{vm}'")
        return self._safe_json(r) or {}

    def power_stop(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/power/stop", f"/api/vcenter/vm/{vm}/power/stop")
        r = self._request("POST", path)
        self._check_response(r, path, f"power off VM '{vm}'")
        return self._safe_json(r) or {}

    def power_reset(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/power/reset", f"/api/vcenter/vm/{vm}/power/reset")
        r = self._request("POST", path)
        self._check_response(r, path, f"reset VM '{vm}'")
        return self._safe_json(r) or {}

    def delete_vm(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}", f"/api/vcenter/vm/{vm}")
        r = self._request("DELETE", path)
        self._check_response(r, path, f"delete VM '{vm}'", allow_statuses=[204])
        return self._safe_json(r) or {}

    # --- Host/Datacenter/Network/Datastore ---

    def list_hosts(self) -> Any:
        path = self._v("/rest/vcenter/host", "/api/vcenter/host")
        r = self._request("GET", path)
        self._check_response(r, path, "list hosts")
        return self._extract_value(r)

    def list_datastores(self) -> Any:
        path = self._v("/rest/vcenter/datastore", "/api/vcenter/datastore")
        r = self._request("GET", path)
        self._check_response(r, path, "list datastores")
        return self._extract_value(r)

    def list_networks(self) -> Any:
        path = self._v("/rest/vcenter/network", "/api/vcenter/network")
        r = self._request("GET", path)
        self._check_response(r, path, "list networks")
        return self._extract_value(r)

    def list_datacenters(self) -> Any:
        path = self._v("/rest/vcenter/datacenter", "/api/vcenter/datacenter")
        r = self._request("GET", path)
        self._check_response(r, path, "list datacenters")
        return self._extract_value(r)

    # --- Snapshots ---

    def list_snapshots(self, vm: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/snapshot", f"/api/vcenter/vm/{vm}/snapshot")
        r = self._request("GET", path)
        self._check_response(r, path, f"list snapshots for VM '{vm}'")
        return self._extract_value(r)

    def create_snapshot(self, vm: str, name: str, description: str = "", memory: bool = False, quiesce: bool = False) -> Any:
        body: Dict[str, Any]
        if self._api_mode == "rest":
            body = {"spec": {"description": description, "memory": memory, "name": name, "quiesce": quiesce}}
        else:
            body = {"description": description, "memory": memory, "name": name, "quiesce": quiesce}
        
        path = self._v(f"/rest/vcenter/vm/{vm}/snapshot", f"/api/vcenter/vm/{vm}/snapshot")
        r = self._request("POST", path, json_body=body)
        self._check_response(r, path, f"create snapshot '{name}' for VM '{vm}'")
        return self._extract_value(r)

    def delete_snapshot(self, vm: str, snapshot: str) -> Any:
        path = self._v(f"/rest/vcenter/vm/{vm}/snapshot/{snapshot}", f"/api/vcenter/vm/{vm}/snapshot/{snapshot}")
        r = self._request("DELETE", path)
        self._check_response(r, path, f"delete snapshot '{snapshot}' for VM '{vm}'", allow_statuses=[204])
        return self._safe_json(r) or {}

    # --- Hardware ---

    def set_cpu(self, vm: str, count: int) -> Any:
        body: Dict[str, Any]
        if self._api_mode == "rest":
            body = {"spec": {"count": count}}
        else:
            body = {"count": count}
        
        path = self._v(f"/rest/vcenter/vm/{vm}/hardware/cpu", f"/api/vcenter/vm/{vm}/hardware/cpu")
        r = self._request("PATCH", path, json_body=body)
        self._check_response(r, path, f"set CPU count to {count} for VM '{vm}'")
        return self._safe_json(r) or {}

    def set_memory(self, vm: str, memory_mib: int) -> Any:
        body: Dict[str, Any]
        if self._api_mode == "rest":
            body = {"spec": {"size_MiB": memory_mib}}
        else:
            body = {"size_MiB": memory_mib}
        
        path = self._v(f"/rest/vcenter/vm/{vm}/hardware/memory", f"/api/vcenter/vm/{vm}/hardware/memory")
        r = self._request("PATCH", path, json_body=body)
        self._check_response(r, path, f"set memory to {memory_mib} MiB for VM '{vm}'")
        return self._safe_json(r) or {}


class VsphereClientPool:
    """
    Thread-safe pool of VsphereClient instances, one per vCenter host.
    
    Reuses authenticated sessions to avoid exhausting vCenter session limits.
    Automatically cleans up sessions on process exit.
    """

    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._clients: Dict[str, VsphereClient] = {}
        self._lock = threading.Lock()
        atexit.register(self.close_all)

    def get(self, hostname: Optional[str] = None) -> VsphereClient:
        """
        Get or create a VsphereClient for the specified host.
        
        Args:
            hostname: Target vCenter hostname. Defaults to configured VCENTER_HOST.
            
        Returns:
            Authenticated VsphereClient instance.
            
        Raises:
            PermissionError: If hostname is not in the allowed hosts list.
        """
        host = (hostname or self._cfg.vsphere.host).strip()
        
        # Enforce allowed hosts
        if self._cfg.vsphere.allowed_hosts and host not in self._cfg.vsphere.allowed_hosts:
            raise PermissionError(f"Hostname '{host}' not in allowed set")

        with self._lock:
            if host in self._clients:
                client = self._clients[host]
                # Ensure still authenticated (may have been invalidated)
                if not client.is_authenticated:
                    client.login()
                return client

            # Create new client with host-specific config
            host_cfg = self._cfg.vsphere.model_copy(deep=True)
            host_cfg.host = host
            
            client = VsphereClient(host_cfg)
            client.login()
            self._clients[host] = client
            logger.info("Created new client for %s (pool size: %d)", host, len(self._clients))
            return client

    def remove(self, hostname: str) -> None:
        """Remove and close a specific client from the pool."""
        with self._lock:
            if hostname in self._clients:
                self._clients[hostname].close()
                del self._clients[hostname]
                logger.info("Removed client for %s from pool", hostname)

    def close_all(self) -> None:
        """Close all clients in the pool. Called automatically on process exit."""
        with self._lock:
            for host, client in list(self._clients.items()):
                try:
                    client.close()
                    logger.debug("Closed client for %s", host)
                except Exception as e:
                    logger.warning("Error closing client for %s: %s", host, e)
            self._clients.clear()
            logger.info("Closed all clients in pool")

    @property
    def size(self) -> int:
        """Number of clients in the pool."""
        with self._lock:
            return len(self._clients)

    @property
    def hosts(self) -> list[str]:
        """List of hosts with active clients."""
        with self._lock:
            return list(self._clients.keys())
