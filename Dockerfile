FROM python:3.11-slim

# Security: non-root user
RUN adduser --disabled-password --gecos "" appuser

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

COPY vsphere_mcp_pro /app/vsphere_mcp_pro
COPY env.example /app/env.example

USER appuser

EXPOSE 8000
ENTRYPOINT ["vsphere-mcp-pro"]
