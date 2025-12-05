# vsphere-mcp-pro

Secure, feature-rich MCP server for VMware vCenter 8.0+.

## Highlights
- SSL verify on by default, optional CA bundle
- vCenter host allow-list
- Bearer token auth + role→tools gating
- Destructive ops require `confirm=True`
- Rate limiting + JSON-lines audit
- Supports `/api` (preferred) and `/rest` endpoints

## Quickstart
```bash
cp .env.example .env
# Fill VCENTER_* and tokens
python -m vsphere_mcp_pro.server

# Docker
docker build -t vsphere-mcp-pro:latest .
docker run --rm -p 8000:8000 --env-file .env vsphere-mcp-pro:latest
```
