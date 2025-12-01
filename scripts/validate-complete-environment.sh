#!/bin/bash

echo "=== COMPLETE BENCHMARK ENVIRONMENT VALIDATION ==="
echo

echo "1. CONTAINER STATUS"
echo "==================="
lxc list
echo

echo "2. BASE TEMPLATE VALIDATION"
echo "==========================="
echo "IP Address: 10.0.100.10"
echo -n "SSH Test: "
ssh -i ~/.ssh/ansible_benchmark -o ConnectTimeout=5 -o BatchMode=yes ansible@10.0.100.10 "echo '✓ Connected'" 2>/dev/null && echo "✓ SUCCESS" || echo "✗ FAILED"

echo -n "Sudo Test: "
ssh -i ~/.ssh/ansible_benchmark -o BatchMode=yes ansible@10.0.100.10 "sudo whoami" 2>/dev/null | grep -q root && echo "✓ SUCCESS" || echo "✗ FAILED"

echo -n "Package Manager: "
ssh -i ~/.ssh/ansible_benchmark -o BatchMode=yes ansible@10.0.100.10 "apt update > /dev/null 2>&1 && echo '✓ WORKING'" 2>/dev/null && echo "✓ WORKING" || echo "✗ FAILED"
echo

echo "3. SCALING NODES VALIDATION"
echo "==========================="
SCALING_LEVELS=(1 3 5 10 15 20)
SUCCESS_COUNT=0
TOTAL_NODES=0

for level in "${SCALING_LEVELS[@]}"; do
    echo "Testing $level node(s):"
    NODE_COUNT=0
    for i in $(seq 1 $level); do
        NODE_IP="10.0.100.$((10 + i))"
        if ssh -i ~/.ssh/ansible_benchmark -o ConnectTimeout=3 -o BatchMode=yes ansible@"$NODE_IP" "echo -n" 2>/dev/null; then
            NODE_COUNT=$((NODE_COUNT + 1))
            SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        fi
        TOTAL_NODES=$((TOTAL_NODES + 1))
    done
    echo "  ✓ $NODE_COUNT/$level nodes responsive"
done
echo

echo "4. RESOURCE LIMITS VERIFICATION"
echo "==============================="
echo "Base Template Resources:"
echo -n "CPU Cores: " && lxc exec ansible-base-template -- nproc
echo -n "Memory: " && lxc exec ansible-base-template -- free -h | grep Mem | awk '{print $2}'
echo -n "Disk: " && lxc exec ansible-base-template -- df -h / | tail -1 | awk '{print $2}'
echo

echo "5. NETWORK CONFIGURATION"
echo "========================"
echo "Base Template Network:"
lxc exec ansible-base-template -- ip addr show eth0 | grep inet
lxc exec ansible-base-template -- ip route show
echo

echo "6. PERFORMANCE TEST"
echo "==================="
echo "Testing concurrent SSH connections..."
for i in {1..5}; do
    NODE_IP="10.0.100.$((10 + i))"
    time ssh -i ~/.ssh/ansible_benchmark -o BatchMode=yes ansible@"$NODE_IP" "hostname" > /dev/null 2>&1 &
done
wait
echo

echo "=== VALIDATION SUMMARY ==="
echo "Total Nodes Tested: $TOTAL_NODES"
echo "Successful Connections: $SUCCESS_COUNT"
echo "Success Rate: $((SUCCESS_COUNT * 100 / TOTAL_NODES))%"

if [ $SUCCESS_COUNT -eq $TOTAL_NODES ]; then
    echo "🎉 ENVIRONMENT VALIDATION: COMPLETE SUCCESS 🎉"
else
    echo "⚠️  ENVIRONMENT VALIDATION: PARTIAL SUCCESS"
    echo "Some nodes may need manual configuration"
fi
