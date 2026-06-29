#!/usr/bin/env bash
# Create connector: Apache Kafka Wiki (confluence, kb-03)
# Usage: BASE_URL=http://localhost:8000 ./create_connector_kafka_confluence.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

# -- KB check / create --
kb_status=$(curl -so /dev/null -w "%{http_code}" "${BASE_URL}/api/kb/kb-03")
if [[ "$kb_status" == "404" ]]; then
    echo "KB not found: kb-03 — creating ..."
    curl -sf -X POST "${BASE_URL}/api/kb" \
        -H "Content-Type: application/json" \
        -d '{"kb_id": "kb-03", "kb_name": ""}' | jq .
    echo ""
else
    echo "KB exists: kb-03"
fi

# -- Create connector --
echo "Creating connector: Apache Kafka Wiki ..."
curl -sf -X POST "${BASE_URL}/api/connectors" \
    -H "Content-Type: application/json" \
    -d '{
        "kb_id": "kb-03",
        "name": "Apache Kafka Wiki",
        "source_type": "confluence",
        "config": {
            "base_url": "https://cwiki.apache.org/confluence",
            "space_key": "KAFKA",
            "max_pages": 100,
            "max_attachment_mb": 10,
            "request_delay_ms": 500
        },
        "sync_schedule": null,
        "schedule_enabled": false
    }' | jq .
