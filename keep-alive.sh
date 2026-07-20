#!/bin/bash
URL="${1:-https://jira-ai-agent.vercel.app}"
echo "Pinging $URL every 30s. Ctrl+C to stop."
while true; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$URL")
  echo "$(date '+%H:%M:%S') $STATUS"
  sleep 30
done
