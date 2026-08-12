#!/bin/bash
set -e

# Compatibility entry point for a manual/cron run. The PostgreSQL worker owns
# both scheduled and on-demand audits; this command processes one queued item.
cd "$(dirname "$0")/.."
exec python -m services.audit_worker --once
