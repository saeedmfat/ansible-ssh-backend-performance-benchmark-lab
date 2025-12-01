#!/bin/bash
CONTAINER_NAME=$1
OUTPUT_FILE=${2:-/tmp/resources.csv}

echo "timestamp,cpu_percent,memory_used_mb,memory_total_mb" > $OUTPUT_FILE

while true; do
    TIMESTAMP=$(date +%Y-%m-%d_%H:%M:%S.%3N)
    
    # Get CPU and memory usage
    RESOURCES=$(lxc info $CONTAINER_NAME --resources)
    
    CPU_PERCENT=$(echo "$RESOURCES" | grep "CPU usage:" | awk '{print $3}')
    MEMORY_USED=$(echo "$RESOURCES" | grep "Memory usage:" | awk '{print $3}')
    MEMORY_TOTAL=$(echo "$RESOURCES" | grep "Memory (current):" | awk '{print $3}')
    
    # Convert memory to MB
    MEMORY_USED_MB=$(echo "scale=2; $MEMORY_USED / 1024 / 1024" | bc)
    MEMORY_TOTAL_MB=$(echo "scale=2; $MEMORY_TOTAL / 1024 / 1024" | bc)
    
    echo "$TIMESTAMP,$CPU_PERCENT,$MEMORY_USED_MB,$MEMORY_TOTAL_MB" >> $OUTPUT_FILE
    sleep 0.5
done
