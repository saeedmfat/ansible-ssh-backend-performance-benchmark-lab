#!/bin/bash

echo "Ensuring all benchmark nodes are ready..."

# Check LXC containers
echo "Checking LXC containers..."
CONTAINERS=$(lxc list --format csv | cut -d, -f1)

EXPECTED_CONTAINERS=25
ACTUAL_CONTAINERS=$(echo "$CONTAINERS" | wc -l)

if [ "$ACTUAL_CONTAINERS" -lt "$EXPECTED_CONTAINERS" ]; then
    echo "Creating benchmark nodes..."
    ~/ansible-benchmark/scripts/create-benchmark-nodes.sh
fi

# Check SSH connectivity
echo "Testing SSH connectivity to nodes..."
FAILED_NODES=0

for container in $CONTAINERS; do
    IP=$(lxc list "$container" --format csv | cut -d, -f4 | tr -d ' ')
    if [ -n "$IP" ]; then
        if timeout 5 ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no ansible@$IP "echo connected" &>/dev/null; then
            echo "  ✓ $container ($IP)"
        else
            echo "  ✗ $container ($IP) - SSH failed"
            FAILED_NODES=$((FAILED_NODES + 1))
        fi
    fi
done

if [ $FAILED_NODES -eq 0 ]; then
    echo "✓ All nodes ready for benchmarking"
else
    echo "✗ $FAILED_NODES nodes have SSH issues"
    echo "Please fix SSH connectivity before continuing"
    exit 1
fi
