#!/usr/bin/env bash
# Create connector: k8s (github, kb-04)
# Usage: BASE_URL=http://localhost:8000 ./create_connector_github_k8s.sh
#
# NOTE: auth_token_secret must be set to a valid GitHub token secret env key.
#       The value stored in DB is encrypted — set it here in plaintext.
#       Example: GITHUB_TOKEN env var must be available in the rag-api container.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
AUTH_TOKEN_SECRET="${AUTH_TOKEN_SECRET:-GITHUB_TOKEN}"

# -- KB check / create --
kb_status=$(curl -so /dev/null -w "%{http_code}" "${BASE_URL}/api/kb/kb-04")
if [[ "$kb_status" == "404" ]]; then
    echo "KB not found: kb-04 — creating ..."
    curl -sf -X POST "${BASE_URL}/api/kb" \
        -H "Content-Type: application/json" \
        -d '{"kb_id": "kb-04", "kb_name": "gitops-demo"}' | jq .
    echo ""
else
    echo "KB exists: kb-04"
fi

# -- Create connector --
echo "Creating connector: GitHub k8s ..."
curl -sf -X POST "${BASE_URL}/api/connectors" \
    -H "Content-Type: application/json" \
    -d "{
        \"kb_id\": \"kb-04\",
        \"name\": \"GitHub k8s\",
        \"source_type\": \"github\",
        \"config\": {
            \"owner\": \"cnapcloud\",
            \"repo\": \"k8s\",
            \"branch\": \"main\",
            \"auth_token_secret\": \"${AUTH_TOKEN_SECRET}\"
        },
        \"sync_schedule\": null,
        \"schedule_enabled\": false
    }" | jq .
