#!/usr/bin/env bash
# Create connector: CNAP Cloud Blog (web, kb-01)
# Usage: BASE_URL=http://localhost:8000 ./create_connector_cnap_blog.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

# -- KB check / create --
kb_status=$(curl -so /dev/null -w "%{http_code}" "${BASE_URL}/api/kb/kb-01")
if [[ "$kb_status" == "404" ]]; then
    echo "KB not found: kb-01 — creating ..."
    curl -sf -X POST "${BASE_URL}/api/kb" \
        -H "Content-Type: application/json" \
        -d '{"kb_id": "kb-01", "kb_name": "지식베이스 01"}' | jq .
    echo ""
else
    echo "KB exists: kb-01"
fi

# -- Create connector --
echo "Creating connector: CNAP Cloud Blog ..."
curl -sf -X POST "${BASE_URL}/api/connectors" \
    -H "Content-Type: application/json" \
    -d '{
        "kb_id": "kb-01",
        "name": "CNAP Cloud Blog",
        "source_type": "web",
        "config": {
            "seed_urls": ["https://cnapcloud.com/blog"],
            "depth": 2,
            "max_pages": 100,
            "include_patterns": [],
            "exclude_patterns": [],
            "request_delay_ms": 100
        },
        "sync_schedule": null,
        "schedule_enabled": false
    }' | jq .
