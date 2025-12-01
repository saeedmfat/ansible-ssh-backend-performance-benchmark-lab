#!/bin/bash

BACKEND="$1"

if [ -z "$BACKEND" ]; then
    echo "Usage: $0 {controlpersist|paramiko}"
    echo "Current backend: $(grep 'ansible_connection' ~/ansible-benchmark/inventory.ini | head -1 | cut -d'=' -f2 2>/dev/null || echo 'not set')"
    exit 1
fi

# Create backup of inventory
cp ~/ansible-benchmark/inventory.ini ~/ansible-benchmark/inventory.ini.backup

# Remove existing connection settings from [all_targets:vars] section
sed -i '/^ansible_connection/d' ~/ansible-benchmark/inventory.ini
sed -i '/^ansible_ssh_args/d' ~/ansible-benchmark/inventory.ini

case $BACKEND in
    controlpersist)
        # Add ControlPersist settings to [all_targets:vars]
        sed -i '/\[all_targets:vars\]/a ansible_connection=ssh' ~/ansible-benchmark/inventory.ini
        sed -i '/ansible_connection=ssh/a ansible_ssh_args=-o ControlMaster=auto -o ControlPersist=60s -o ControlPath=~/.ssh/ansible-%%r@%%h:%%p' ~/ansible-benchmark/inventory.ini
        echo "✓ Switched to ControlPersist backend"
        ;;
        
    paramiko)
        # Add Paramiko settings to [all_targets:vars]
        sed -i '/\[all_targets:vars\]/a ansible_connection=paramiko' ~/ansible-benchmark/inventory.ini
        echo "✓ Switched to Paramiko backend"
        ;;
        
    *)
        echo "Error: Unknown backend '$BACKEND'"
        echo "Available backends: controlpersist, paramiko"
        exit 1
        ;;
esac

echo "Testing connectivity with $BACKEND backend..."
ansible targets_1 -m ping
