#!/bin/bash

# Find the most recent PID file
PID_FILE=$(find ~/ansible-benchmark/results -name "monitor_pids_*.txt" 2>/dev/null | sort | tail -1)

if [ -z "$PID_FILE" ] || [ ! -f "$PID_FILE" ]; then
    echo "No active monitoring sessions found"
    exit 1
fi

echo "Stopping monitoring from PID file: $PID_FILE"
pids=$(cat "$PID_FILE")
kill $pids 2>/dev/null
rm -f "$PID_FILE"
echo "Monitoring stopped"
