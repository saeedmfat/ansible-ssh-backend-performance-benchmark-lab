#!/bin/bash

BASE_NAME="benchmark-node"
TOTAL_NODES=25
START_IP=11

echo "=== CREATING $TOTAL_NODES BENCHMARK NODES ==="
echo

# Stop and delete any existing benchmark nodes (clean start)
echo "Cleaning up existing benchmark nodes..."
for node in $(lxc list --format csv -c n | grep benchmark-node); do
    echo "Deleting existing node: $node"
    lxc delete "$node" --force
done

echo
echo "Creating new benchmark nodes with static IPs..."

for i in $(seq 1 $TOTAL_NODES); do
    NODE_NAME="${BASE_NAME}-$(printf '%02d' $i)"
    NODE_IP="10.0.100.$((START_IP + i - 1))"
    
    echo
    echo "=== Creating $NODE_NAME ==="
    echo "IP Address: $NODE_IP"
    
    # Copy from base template
    echo "Copying from base template..."
    lxc copy ansible-base-template "$NODE_NAME"
    
    # Configure static IP
    echo "Setting static IP..."
    lxc config device set "$NODE_NAME" eth0 ipv4.address="$NODE_IP"
    
    # Start the container
    echo "Starting container..."
    lxc start "$NODE_NAME"
    
    # Wait for container to be ready
    echo "Waiting for container to be ready..."
    sleep 5
    
    # Verify the container has the correct IP
    ACTUAL_IP=$(lxc list "$NODE_NAME" --format csv -c 4 | cut -d' ' -f1)
    if [ "$ACTUAL_IP" = "$NODE_IP" ]; then
        echo "✓ $NODE_NAME successfully created at $NODE_IP"
    else
        echo "✗ IP mismatch: Expected $NODE_IP, got $ACTUAL_IP"
    fi
done

echo
echo "=== NODE CREATION COMPLETE ==="
echo
echo "Summary of created nodes:"
lxc list | grep benchmark-node
