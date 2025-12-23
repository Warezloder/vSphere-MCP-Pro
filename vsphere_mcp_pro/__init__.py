"""
vSphere-MCP-Pro: A secure MCP server for VMware vCenter 8.0+.

This package provides a Model Context Protocol (MCP) server for VMware vCenter
operations including VM lifecycle management, snapshots, and inventory discovery.
"""

from .vsphere_client import VsphereApiError, VsphereClient, VsphereClientPool
from .config import AppConfig, load_config
from .authz import Authorizer, TokenBucketLimiter
from .audit import Auditor, AuditEvent

__version__ = "0.2.0"

__all__ = [
    # Client
    "VsphereClient",
    "VsphereClientPool",
    "VsphereApiError",
    # Config
    "AppConfig",
    "load_config",
    # Auth
    "Authorizer",
    "TokenBucketLimiter",
    # Audit
    "Auditor",
    "AuditEvent",
]
