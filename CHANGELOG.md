# Changelog

All notable changes to vSphere-MCP-Pro will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2025-12-23

### Added

- **`VsphereApiError` exception class** - Custom exception with rich error context including:
  - HTTP status code
  - vCenter error type extraction (supports both `/api` and `/rest` response formats)
  - Human-readable error messages from vCenter
  - Convenience properties: `is_not_found`, `is_unauthorized`, `is_forbidden`, `is_conflict`

- **`VsphereClientPool` class** - Thread-safe connection pooling:
  - Maintains one authenticated session per vCenter host
  - Automatic session reuse to prevent vCenter session exhaustion
  - `atexit` hook for graceful cleanup on process termination
  - `get()`, `remove()`, `close_all()` methods
  - `size` and `hosts` properties for observability

- **`VsphereClient.logout()` method** - Properly terminates vCenter sessions via DELETE to session endpoint

- **`VsphereClient.close()` method** - Calls `logout()` then closes the underlying `requests.Session`

- **`VsphereClient.host` property** - Clean accessor for the configured hostname

- **`VsphereClient.is_authenticated` property** - Check if session token is present

- **Response validation** - All API methods now validate responses via `_check_response()`:
  - Raises `VsphereApiError` on non-2xx responses
  - Supports `allow_statuses` for operations like DELETE that return 204
  - Descriptive error messages include operation context

- **Helper methods in `VsphereClient`**:
  - `_safe_json()` - Safely parse JSON responses without raising
  - `_check_response()` - Validate HTTP response and raise on error
  - `_extract_value()` - Handle `/api` vs `/rest` response format differences

### Changed

- **Fixed decorator pattern in `server.py`** - Converted `inject` from broken function to proper decorator factory:
  ```python
  # Before (broken - caused TypeError)
  @inject
  def list_vms(...): ...
  
  # After (working)
  @inject("list_vms")
  def list_vms(...): ...
  ```

- **Destructive operations now properly flagged** - Added `destructive=True` to:
  - `delete_vm`
  - `delete_vm_snapshot`
  - `modify_vm_resources`

- **Session management refactored** - Replaced per-request client creation with `VsphereClientPool`:
  - Single pool instance created in `build_server()`
  - Pool injected into all tools via `_pool` parameter
  - Significantly reduces vCenter session consumption

- **Improved error messages** - API errors now include full context:
  ```
  VsphereApiError: Failed to get VM 'vm-999': HTTP 404 on /api/vcenter/vm/vm-999 [NOT_FOUND]: The VM was not found.
  ```

### Fixed

- **Dockerfile path error** - Changed `COPY src /app/src` to `COPY vsphere_mcp_pro /app/vsphere_mcp_pro`

- **Session leak** - Previous implementation created new session per API call without logout; now properly pooled and cleaned up

- **Silent API failures** - Methods previously returned error JSON as if successful; now raise `VsphereApiError`

### Deprecated

- None

### Removed

- `client_for()` helper function in `server.py` - Replaced by `VsphereClientPool.get()`

### Security

- Sessions are now properly terminated on shutdown via `atexit` hook
- Reduced attack surface by limiting active vCenter sessions

## [0.1.0] - Initial Release

### Added

- Initial MCP server implementation for VMware vCenter 8.0+
- VM lifecycle management (power on/off/reset, delete)
- Snapshot operations (list, create, delete)
- Inventory discovery (VMs, hosts, datastores, networks, datacenters)
- Resource modification (CPU, memory)
- Token-based RBAC authorization
- Token bucket rate limiting
- JSONL audit logging
- SSL verification with optional CA bundle
- Allowed-host enforcement
- Support for both `/api` and `/rest` vCenter endpoints
