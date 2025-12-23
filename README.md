# vSphere-MCP-Pro

A secure, feature-rich Model Context Protocol (MCP) server for VMware vCenter 8.0+.

Exposes controlled vCenter operations via MCP tools including VM lifecycle management, snapshot operations, datastore/host discovery, and more—with audit logging, RBAC authorization, session pooling, and rate limiting.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Directory Structure](#directory-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Server](#running-the-server)
- [Available Tools / API](#available-tools--api)
- [Error Handling](#error-handling)
- [Audit Logging](#audit-logging)
- [Rate Limiting](#rate-limiting)
- [Security Model](#security-model)
- [Development](#development)
- [Docker Usage](#docker-usage)
- [Troubleshooting](#troubleshooting)
- [Changelog](#changelog)
- [License](#license)

---

## Overview

`vsphere-mcp-pro` is an MCP server designed for VMware vCenter 8.0+ environments.

It provides:

- Safe, structured access to vCenter operations
- Strict authorization via roles → allowed tools
- Snapshot + VM lifecycle operations
- Auditing and rate limiting for secure multi-tenant use
- Support for both `/api` (preferred) and `/rest` vCenter endpoints
- Optional host allow-listing to prevent accidental cross-cluster operations
- Connection pooling to prevent vCenter session exhaustion

The server runs using `FastMCP` and automatically wraps every tool operation with:

- Token-based RBAC (`Authorizer`)
- Token bucket rate limiting
- JSONL audit logging
- Confirmation requirement for destructive operations
- Proper error handling with detailed vCenter error context

---

## Key Features

### ✔ Secure by design

- SSL verification enabled by default
- Optional CA bundle support
- Allowed-host enforcement prevents unauthorized vCenter targets

### ✔ Strong authorization model

- Token → role mapping
- Role → allowed-tools mapping
- Enforced unless explicitly disabled
- Destructive operations require `confirm=True`

### ✔ Operationally robust

- Automatic retry logic for vCenter API calls (`Retry + HTTPAdapter`)
- Session auto-renewal on 401
- Connection pooling with automatic cleanup
- Proper session logout on shutdown
- Extensive logging for auditing and observability
- Rich error messages with vCenter error context

### ✔ High performance

- Thread-safe vCenter session pooling (one session per host)
- Eliminates per-request authentication overhead
- MCP server built with `uvicorn`

---

## Architecture

**Key modules:**

- **`server.py`**
  Builds the MCP server, registers all tools, injects authorization, rate-limiting, session pool, and auditing wrappers.

- **`vsphere_client.py`**
  Handles retries, authentication, session pooling, and REST/API mode switching for VMware vCenter. Includes:
  - `VsphereClient` - Thread-safe vCenter REST API client
  - `VsphereClientPool` - Connection pool with automatic cleanup
  - `VsphereApiError` - Rich exception class for API errors

- **`authz.py`**
  Implements:
  - Token → role resolution
  - Role → tool gating
  - Token bucket rate limiting

- **`audit.py`**
  Writes JSON-lines logs for every operation.

- **`config.py`**
  Loads environment variables into a typed `AppConfig` using `pydantic`.

---

## Directory Structure

```
/
├── vsphere_mcp_pro/          # Python package
│   ├── __init__.py
│   ├── server.py             # MCP server and tool definitions
│   ├── vsphere_client.py     # vCenter client, pool, and exceptions
│   ├── authz.py              # Authorization and rate limiting
│   ├── audit.py              # Audit logging
│   └── config.py             # Configuration loading
├── pyproject.toml            # Project metadata and dependencies
├── README.md
├── CHANGELOG.md
├── LICENSE
├── env.example               # Example environment configuration
└── Dockerfile
```

---

## Installation

### Prerequisites

- Python **3.10+**
- VMware vCenter **8.0+**
- Valid API credentials

### Install from source

```bash
git clone https://github.com/Warezloder/vSphere-MCP-Pro
cd vSphere-MCP-Pro
pip install -e .
```

---

## Configuration

Configuration is environment-driven. Copy the example file:

```bash
cp env.example .env
```

### Required Environment Variables

| Variable                | Description                                   |
| ----------------------- | --------------------------------------------- |
| `VCENTER_HOST`          | vCenter hostname/IP                           |
| `VCENTER_USER`          | vCenter username                              |
| `VCENTER_PASSWORD`      | vCenter password                              |
| `ROLES_TO_TOOLS`        | JSON map of role → allowed tools              |
| `TOKENS_TO_ROLES`       | JSON map of token → role                      |
| `ALLOWED_VCENTER_HOSTS` | Optional allowlist for multi-host deployments |

### Optional Environment Variables

| Variable             | Default              | Description                          |
| -------------------- | -------------------- | ------------------------------------ |
| `VSPHERE_API_MODE`   | `api`                | API mode: `api` or `rest`            |
| `INSECURE`           | `false`              | Disable SSL verification             |
| `VCENTER_CA_BUNDLE`  |                      | Path to custom CA bundle             |
| `VCENTER_TIMEOUT_S`  | `20`                 | Request timeout in seconds           |
| `VCENTER_RETRIES`    | `3`                  | Number of retry attempts             |
| `VCENTER_BACKOFF`    | `0.5`                | Retry backoff factor                 |
| `SERVER_HOST`        | `0.0.0.0`            | Server bind address                  |
| `SERVER_PORT`        | `8000`               | Server port                          |
| `MCP_PATH`           | `/mcp`               | MCP endpoint path                    |
| `AUDIT_LOG_PATH`     |                      | Audit log file (blank = stdout)      |
| `AUTH_ENFORCE`       | `true`               | Enforce RBAC                         |
| `RATE_LIMIT`         | `true`               | Enable rate limiting                 |
| `RATE_LIMIT_RPS`     | `5`                  | Requests per second                  |
| `RATE_LIMIT_BURST`   | `10`                 | Burst allowance                      |

### Example Configuration

```bash
VCENTER_HOST=vcenter.example.com
VCENTER_USER=administrator@vsphere.local
VCENTER_PASSWORD=s3cret
TOKENS_TO_ROLES={"token1": "read", "token2": "ops", "token3": "admin"}
ROLES_TO_TOOLS={"read":["list_vms","get_vm_details"],"ops":["power_on_vm","power_off_vm"],"admin":["delete_vm"]}
```

---

## Running the Server

### Local execution

```bash
python -m vsphere_mcp_pro.server
```

Server defaults (override via env vars):

- Host: `0.0.0.0`
- Port: `8000`
- MCP path: `/mcp`

---

## Available Tools / API

Below is a categorized summary of available MCP tools exposed by the server.

### VM Discovery

| Tool              | Description           |
| ----------------- | --------------------- |
| `list_vms`        | List all VMs          |
| `get_vm_details`  | Get VM details by ID  |

### Inventory Discovery

| Tool                             | Description                    |
| -------------------------------- | ------------------------------ |
| `list_hosts`                     | List ESXi hosts                |
| `list_datastores`                | List datastores                |
| `list_networks`                  | List networks                  |
| `list_datacenters`               | List datacenters               |
| `get_datastore_usage`            | Get datastore capacity/usage   |
| `get_resource_utilization_summary` | Summary of all resources     |

### Power Operations

| Tool           | Description      |
| -------------- | ---------------- |
| `power_on_vm`  | Power on a VM    |
| `power_off_vm` | Power off a VM   |
| `restart_vm`   | Restart a VM     |

### Snapshot Operations

| Tool                 | Description                              |
| -------------------- | ---------------------------------------- |
| `list_vm_snapshots`  | List snapshots for a VM                  |
| `create_vm_snapshot` | Create a snapshot                        |
| `delete_vm_snapshot` | Delete a snapshot (**requires confirm**) |

### Destructive Operations (require `confirm=True`)

| Tool                  | Description                        |
| --------------------- | ---------------------------------- |
| `delete_vm`           | Permanently delete a VM            |
| `delete_vm_snapshot`  | Delete a snapshot                  |
| `modify_vm_resources` | Modify CPU/memory (requires power off) |

---

## Error Handling

The server provides rich error context via the `VsphereApiError` exception:

```
VsphereApiError: Failed to get VM 'vm-999': HTTP 404 on /api/vcenter/vm/vm-999 [NOT_FOUND]: The VM was not found.
```

Error responses include:

- HTTP status code
- API path
- vCenter error type (e.g., `NOT_FOUND`, `ALREADY_EXISTS`)
- Human-readable error messages from vCenter

The exception provides convenience properties:

- `is_not_found` - 404 or NOT_FOUND error
- `is_unauthorized` - 401 error
- `is_forbidden` - 403 error
- `is_conflict` - 409 error

---

## Audit Logging

Every MCP tool call is logged as a JSON line containing:

- Tool name
- Execution status (ok/error)
- Duration (ms)
- Sanitized arguments (passwords & tokens masked)
- Error message (if any)
- Role + host context

Logs write to stdout by default, or to `AUDIT_LOG_PATH` if configured.

---

## Rate Limiting

Uses a token-bucket strategy:

- Configurable `RATE_LIMIT_RPS` and `RATE_LIMIT_BURST`
- Separate buckets per token
- Disabled by setting `RATE_LIMIT=false`

---

## Security Model

| Mechanism              | Purpose                                   |
| ---------------------- | ----------------------------------------- |
| SSL verification       | Prevent MITM attacks                      |
| Allowed-host list      | Prevent unauthorized target selection     |
| Role → tool mapping    | Enforce least-privilege principle         |
| Token authentication   | Multi-tenant safe access                  |
| Required confirmations | Prevent accidental destructive operations |
| Rate limiting          | Protects vCenter and MCP server           |
| Session pooling        | Prevents vCenter session exhaustion       |

---

## Development

### Install dev deps

```bash
pip install -e .[dev]
```

### Run with autoreload

```bash
uvicorn vsphere_mcp_pro.server:main --reload
```

---

## Docker Usage

### Build

```bash
docker build -t vsphere-mcp-pro .
```

### Run

```bash
docker run \
  --rm \
  -p 8000:8000 \
  --env-file .env \
  vsphere-mcp-pro
```

---

## Troubleshooting

### "login failed: HTTP 401"

- Verify vCenter username/password
- Ensure correct API mode (`VSPHERE_API_MODE=api|rest`)

### "Hostname not in allowed set"

- Add the hostname to `ALLOWED_VCENTER_HOSTS`

### Rate limit errors

- Increase `RATE_LIMIT_BURST`
- Adjust per-token usage

### SSL certificate issues

- Set `VCENTER_CA_BUNDLE` to your CA bundle path
- Or disable SSL verification (not recommended): `INSECURE=true`

### VsphereApiError exceptions

- Check the error message for vCenter-specific details
- Use `error.is_not_found`, `error.is_forbidden`, etc. for programmatic handling
- Verify the VM/resource ID exists

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and changes.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
