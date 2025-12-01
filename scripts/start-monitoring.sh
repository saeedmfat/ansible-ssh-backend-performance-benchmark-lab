#!/bin/bash

OUTPUT_DIR="${1:-~/ansible-benchmark/results}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$OUTPUT_DIR"

echo "Starting system monitoring..."
echo "Output directory: $OUTPUT_DIR"
echo "Timestamp: $TIMESTAMP"

# Check if mpstat is available, if not use alternative method
if command -v mpstat > /dev/null 2>&1; then
    CPU_CMD="mpstat 1 1 | awk '/Average:/ {print 100 - \$12}' | tail -1"
else
    CPU_CMD="top -bn2 | grep 'Cpu(s)' | tail -1 | awk '{print 100 - \$8}'"
fi

# Start host system monitoring
echo "timestamp,cpu_percent,memory_percent,load_1,load_5,load_15" > "$OUTPUT_DIR/host_resources_$TIMESTAMP.csv"

# Function to monitor host resources
monitor_host() {
    while true; do
        TIMESTAMP_MS=$(date +%Y-%m-%d_%H:%M:%S.%3N)
        
        # CPU usage
        CPU_PERCENT=$(eval $CPU_CMD 2>/dev/null || echo "0")
        
        # Memory usage
        MEM_TOTAL=$(free -m | awk '/Mem:/ {print $2}')
        MEM_USED=$(free -m | awk '/Mem:/ {print $3}')
        if [ "$MEM_TOTAL" -gt 0 ]; then
            MEM_PERCENT=$(echo "scale=2; $MEM_USED * 100 / $MEM_TOTAL" | bc 2>/dev/null || echo "0")
        else
            MEM_PERCENT="0"
        fi
        
        # Load average
        LOAD=$(cat /proc/loadavg 2>/dev/null | awk '{print $1","$2","$3}' || echo "0,0,0")
        
        echo "$TIMESTAMP_MS,$CPU_PERCENT,$MEM_PERCENT,$LOAD" >> "$OUTPUT_DIR/host_resources_$TIMESTAMP.csv"
        sleep 2
    done
}

# Function to monitor LXD containers
monitor_containers() {
    echo "timestamp,container,cpu_percent,memory_used_mb,memory_total_mb" > "$OUTPUT_DIR/container_resources_$TIMESTAMP.csv"
    
    while true; do
        TIMESTAMP_MS=$(date +%Y-%m-%d_%H:%M:%S.%3N)
        
        for container in $(lxc list --format csv -c n 2>/dev/null | grep -E "(benchmark-node|ansible-base)"); do
            if lxc info "$container" > /dev/null 2>&1; then
                RESOURCES=$(lxc info "$container" --resources 2>/dev/null)
                CPU_PERCENT=$(echo "$RESOURCES" | grep "CPU usage:" | awk '{print $3}' | sed 's/%//' || echo "0")
                MEMORY_USED=$(echo "$RESOURCES" | grep "Memory usage:" | awk '{print $3}' || echo "0")
                MEMORY_TOTAL=$(echo "$RESOURCES" | grep "Memory (current):" | awk '{print $3}' || echo "0")
                
                # Convert bytes to MB if we have numeric values
                if echo "$MEMORY_USED" | grep -qE '^[0-9]+$' && echo "$MEMORY_TOTAL" | grep -qE '^[0-9]+$'; then
                    MEMORY_USED_MB=$(echo "scale=2; $MEMORY_USED / 1024 / 1024" | bc 2>/dev/null || echo "0")
                    MEMORY_TOTAL_MB=$(echo "scale=2; $MEMORY_TOTAL / 1024 / 1024" | bc 2>/dev/null || echo "0")
                else
                    MEMORY_USED_MB="0"
                    MEMORY_TOTAL_MB="0"
                fi
                
                echo "$TIMESTAMP_MS,$container,$CPU_PERCENT,$MEMORY_USED_MB,$MEMORY_TOTAL_MB" >> "$OUTPUT_DIR/container_resources_$TIMESTAMP.csv"
            fi
        done
        sleep 5
    done
}

# Start monitoring in background
monitor_host &
HOST_MONITOR_PID=$!
sleep 1

monitor_containers &
CONTAINER_MONITOR_PID=$!

echo "Monitoring started with PIDs:"
echo "Host monitor: $HOST_MONITOR_PID"
echo "Container monitor: $CONTAINER_MONITOR_PID"
echo
echo "To stop monitoring, run: ~/ansible-benchmark/scripts/stop-monitoring.sh"
echo
echo "Monitoring output:"
echo "- Host resources: $OUTPUT_DIR/host_resources_$TIMESTAMP.csv"
echo "- Container resources: $OUTPUT_DIR/container_resources_$TIMESTAMP.csv"

# Save PIDs for later cleanup
echo "$HOST_MONITOR_PID $CONTAINER_MONITOR_PID" > "$OUTPUT_DIR/monitor_pids_$TIMESTAMP.txt"
