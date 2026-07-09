#!/bin/bash
# Scheduled queue run. Loads env (API keys) and runs all active clients.
cd /opt/seo-agent/pipeline
export OPENROUTER_API_KEY="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"
export OPENROUTER_MODEL="z-ai/glm-5.2"
export DFS_LOGIN="habrelias06@gmail.com"
export DFS_PASS="ea4e008a7c8fb4db"
/opt/seo-agent/pipeline/venv/bin/python3 queue_run.py run >> /opt/seo-agent/pipeline/scheduled.log 2>&1
