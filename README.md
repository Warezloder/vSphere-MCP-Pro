# vSphere-MCP-Pro

A secure, feature-rich Machine Control Plane (MCP) server for VMware vCenter 8.0+.  
This service exposes a controlled set of vCenter operations via MCP tools, including VM lifecycle management, snapshot operations, datastore/host discovery, and more—wrapped with audit logging, RBAC authorization, and rate limiting.

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
- [Audit Logging](#audit-logging)
- [Rate Limiting](#rate-limiting)
- [Security Model](#security-model)
- [Development](#development)
- [Docker Usage](#docker-usage)
- [Troubleshooting](#troubleshooting)
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

The server runs using `FastMCP` and automatically wraps every tool operation with:
- Token-based RBAC (`Authorizer`)
- Token bucket rate limiting
- JSONL audit logging
- Optional confirmation for destructive operations

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
- Extensive logging for auditing and observability  

### ✔ High performance
- Thread-safe vCenter session management  
- MCP server built with `uvicorn`

---

## Architecture

**Key modules:**

- **`server.py`**  
  Builds the MCP server, registers all tools, injects authorization, rate-limiting, and auditing wrappers.

- **`vsphere_client.py`**  
  Handles retries, authentication, and REST/API mode switching for VMware vCenter.

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

```Structure

/
├── vsphere-mcp-pro/        # Python package
│   ├── server.py
│   ├── vsphere_client.py
│   ├── authz.py
│   ├── audit.py
│   ├── config.py
├── pyproject.toml
├── README.md
├── .env.example
├── Dockerfile

````

---

## Installation

### Prerequisites

- Python **3.10+**
- VMware vCenter **8.0+**
- A valid set of API credentials

### Install from source

```bash

git clone https://github.com/Warezloder/vSphere-MCP-Pro
cd vsphere-mcp-pro
pip install -e .

````

---

## Configuration

Configuration is environment-driven. Copy the example file:

```bash

cp .env.example .env

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

Example snippet:

```python

VCENTER_HOST=vcenter.example.com
VCENTER_USER=administrator@vsphere.local
VCENTER_PASSWORD=s3cret
TOKENS_TO_ROLES={"token1": "read", "token2": "ops"}
ROLES_TO_TOOLS={"read":["list_vms","get_vm_details"],"ops":["power_on_vm"]}

```

---

## Running the Server

### Local execution

```bash

python -m vsphere_mcp_pro.server

```

Server defaults (override via env vars):

* Host: `0.0.0.0`
* Port: `8000`
* MCP path: `/mcp`

---

## Available Tools / API

Below is a categorized summary of available MCP tools exposed by the server.

### VM Discovery

* `list_vms`
* `get_vm_details`

### Inventory Discovery

* `list_hosts`
* `list_datastores`
* `list_networks`
* `list_datacenters`
* `get_datastore_usage`
* `get_resource_utilization_summary`

### Power Operations

* `power_on_vm`
* `power_off_vm`
* `restart_vm`

### Snapshot Operations

* `list_vm_snapshots`
* `create_vm_snapshot`
* `delete_vm_snapshot`

### VM Resource Management

* `modify_vm_resources` (CPU / memory)

### Destructive Operations (require `confirm=True`)

* `delete_vm`
* `delete_vm_snapshot`

---

## Audit Logging

Every MCP tool call is logged as a JSON line containing:

* tool name
* execution status
* duration (ms)
* sanitized arguments (passwords & tokens masked)
* optional error message
* role + host context

Logs either write to stdout or to the configured `AUDIT_LOG_PATH`.

---

## Rate Limiting

Uses a token-bucket strategy:

* Configurable `RATE_LIMIT_RPS` and `RATE_LIMIT_BURST`
* Separate buckets per token
* Disabled by setting `RATE_LIMIT=false`

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

* Verify vCenter username/password
* Ensure correct API mode (`VSPHERE_API_MODE=api|rest`)

### "Hostname not in allowed set"

* Add the hostname to `ALLOWED_VCENTER_HOSTS`

### Rate limit errors

* Increase `RATE_LIMIT_BURST`
* Adjust per-token usage

### SSL certificate issues

* Set `VCENTER_CA_BUNDLE`
  or
* Disable SSL verification only if absolutely necessary:
  `INSECURE=true`

---

## License

This project is licensed under your chosen repository license.
