#!/usr/bin/env bash
# Create connector: Kubernetes Docs (web, kb-02)
# Usage: BASE_URL=http://localhost:8000 ./create_connector_k8s_docs.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

# -- KB check / create --
kb_status=$(curl -so /dev/null -w "%{http_code}" "${BASE_URL}/api/kb/kb-02")
if [[ "$kb_status" == "404" ]]; then
    echo "KB not found: kb-02 — creating ..."
    curl -sf -X POST "${BASE_URL}/api/kb" \
        -H "Content-Type: application/json" \
        -d '{"kb_id": "kb-02", "kb_name": "지식베이스 02"}' | jq .
    echo ""
else
    echo "KB exists: kb-02"
fi

# -- Create connector --
echo "Creating connector: Kubernetes Docs ..."
curl -sf -X POST "${BASE_URL}/api/connectors" \
    -H "Content-Type: application/json" \
    -d '{
        "kb_id": "kb-02",
        "name": "Kubernetes Docs",
        "source_type": "web",
        "config": {
            "seed_urls": ["https://kubernetes.io/docs"],
            "depth": 3,
            "max_pages": 200,
            "include_patterns": [],
            "exclude_patterns": [],
            "request_delay_ms": 0
        },
        "sync_schedule": "0 15 * * *",
        "schedule_enabled": false
    }' | jq .
