#!/bin/bash

SSH_KEY="$HOME/.ssh/ansible_benchmark"

echo "=== SETTING UP SSH KEYS ON ALL BENCHMARK NODES ==="
echo

# First, ensure we have the SSH key on the host
if [ ! -f "$SSH_KEY" ]; then
    echo "Generating new SSH key pair..."
    ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -q
fi

echo "Distributing SSH public key to all nodes..."

SUCCESS_COUNT=0
TOTAL_NODES=0

for node in $(lxc list --format csv -c n | grep benchmark-node); do
    TOTAL_NODES=$((TOTAL_NODES + 1))
    NODE_IP=$(lxc list "$node" --format csv -c 4 | cut -d' ' -f1)
    
    echo
    echo "Configuring $node ($NODE_IP)..."
    
    # Wait a moment for the node to be fully ready
    sleep 2
    
    # Create .ssh directory and set permissions
    lxc exec "$node" -- mkdir -p /home/ansible/.ssh
    lxc exec "$node" -- chown ansible:ansible /home/ansible/.ssh
    lxc exec "$node" -- chmod 700 /home/ansible/.ssh
    
    # Copy the public key
    lxc file push "$SSH_KEY.pub" "$node/home/ansible/.ssh/authorized_keys"
    
    # Set proper ownership and permissions
    lxc exec "$node" -- chown ansible:ansible /home/ansible/.ssh/authorized_keys
    lxc exec "$node" -- chmod 600 /home/ansible/.ssh/authorized_keys
    
    # Test SSH connection
    if ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o BatchMode=yes ansible@"$NODE_IP" "echo 'SSH successful'" 2>/dev/null; then
        echo "✓ SSH configured successfully on $node"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        echo "✗ SSH configuration failed on $node"
        # Try alternative method using lxc exec
        lxc exec "$node" -- bash -c "echo '$(cat $SSH_KEY.pub)' >> /home/ansible/.ssh/authorized_keys"
        lxc exec "$node" -- chown ansible:ansible /home/ansible/.ssh/authorized_keys
        lxc exec "$node" -- chmod 600 /home/ansible/.ssh/authorized_keys
    fi
done

echo
echo "=== SSH KEY SETUP SUMMARY ==="
echo "Successful configurations: $SUCCESS_COUNT/$TOTAL_NODES"
echo
