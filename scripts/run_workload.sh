#!/bin/bash

WORKLOAD="$1"
BACKEND="$2"
TARGETS="$3"

if [ -z "$WORKLOAD" ]; then
    echo "Usage: $0 <workload> [backend] [targets]"
    echo "Available workloads:"
    echo "  connection_intensive    - Tests SSH connection performance"
    echo "  data_transfer_intensive - Tests file transfer performance"
    echo "  mixed_realworld         - Tests real-world operations"
    echo ""
    echo "Available backends:"
    echo "  ssh        - ControlPersist (default)"
    echo "  paramiko   - Paramiko Python SSH"
    echo ""
    echo "Target groups (from inventory):"
    echo "  targets_1, targets_3, targets_5, targets_10, targets_15, targets_20"
    exit 1
fi

# Default values
BACKEND="${2:-ssh}"
TARGETS="${3:-all}"

echo "=== Running Workload Test ==="
echo "Workload: $WORKLOAD"
echo "SSH Backend: $BACKEND"
echo "Targets: $TARGETS"
echo "Timestamp: $(date)"

# Set SSH backend
echo "Setting SSH backend to $BACKEND..."
export ANSIBLE_SSH_ARGS="-o ControlMaster=auto -o ControlPersist=60s"
if [ "$BACKEND" = "paramiko" ]; then
    export ANSIBLE_SSH_ARGS=""
    export ANSIBLE_SSH_TRANSFER_METHOD=smart
fi

# Run the workload
PLAYBOOK="~/ansible-benchmark/workloads/playbooks/${WORKLOAD}.yaml"
if [ -f "$PLAYBOOK" ]; then
    echo "Running playbook: $PLAYBOOK"
    START_TIME=$(date +%s.%N)
    
    ansible-playbook "$PLAYBOOK" \
        -i ~/ansible-benchmark/inventory.ini \
        -l "$TARGETS" \
        -e "ansible_connection=$BACKEND" \
        -v
    
    END_TIME=$(date +%s.%N)
    DURATION=$(echo "$END_TIME - $START_TIME" | bc)
    
    echo ""
    echo "=== Workload Complete ==="
    echo "Duration: $DURATION seconds"
    echo "Backend: $BACKEND"
    echo "Workload: $WORKLOAD"
    echo "Targets: $TARGETS"
    echo "Results logged to: /tmp/benchmark_measurements.csv"
else
    echo "Error: Workload '$WORKLOAD' not found!"
    echo "Available workloads in ~/ansible-benchmark/workloads/playbooks/:"
    ls ~/ansible-benchmark/workloads/playbooks/*.yaml 2>/dev/null | xargs -n1 basename | sed 's/.yaml//'
    exit 1
fi
