#!/bin/bash

echo "=== COMPLETE SETUP VALIDATION ==="
echo

PASS_COUNT=0
FAIL_COUNT=0

test_step() {
    local description="$1"
    local command="$2"
    
    echo -n "Testing: $description... "
    if eval "$command" > /dev/null 2>&1; then
        echo "✓ PASS"
        ((PASS_COUNT++))
        return 0
    else
        echo "✗ FAIL"
        ((FAIL_COUNT++))
        return 1
    fi
}

echo "1. Ansible Configuration Tests"
test_step "Ansible config file" "ansible --version | grep -q '/home/saeed/ansible-benchmark/ansible/ansible.cfg'"
test_step "Inventory accessibility" "test -f ~/ansible-benchmark/inventory.ini"
test_step "SSH key exists" "test -f ~/.ssh/ansible_benchmark"

echo
echo "2. SSH Backend Tests"
test_step "ControlPersist backend" "~/ansible-benchmark/scripts/set-ssh-backend.sh controlpersist > /dev/null 2>&1 && ansible targets_1 -m ping > /dev/null 2>&1"
test_step "Paramiko backend availability" "python3 -c 'import paramiko' 2>/dev/null"

echo
echo "3. Node Connectivity Tests"
test_step "All nodes reachable" "ansible all -m ping > /dev/null 2>&1"
test_step "Scaling group 1" "ansible targets_1 -m ping > /dev/null 2>&1"
test_step "Scaling group 3" "ansible targets_3 -m ping > /dev/null 2>&1"
test_step "Scaling group 5" "ansible targets_5 -m ping > /dev/null 2>&1"
test_step "Sudo privileges" "ansible targets_1 -m shell -a 'whoami' -b | grep -q root"

echo
echo "4. Monitoring System Tests"
test_step "Start monitoring" "~/ansible-benchmark/scripts/start-monitoring.sh > /dev/null 2>&1 & sleep 3"
test_step "Stop monitoring" "~/ansible-benchmark/scripts/stop-monitoring.sh > /dev/null 2>&1"

echo
echo "5. Benchmark System Tests"
test_step "Benchmark script executable" "test -x ~/ansible-benchmark/scripts/run-benchmark.sh"
test_step "Single benchmark run" "~/ansible-benchmark/scripts/run-benchmark.sh controlpersist targets_1 1 > /dev/null 2>&1"
test_step "Results file created" "test -f ~/ansible-benchmark/results/benchmark_results.csv"

echo
echo "6. Workload Playbook Tests"
test_step "CPU workload playbook" "test -f ~/ansible-benchmark/playbooks/cpu_workload.yaml"
test_step "IO workload playbook" "test -f ~/ansible-benchmark/playbooks/io_workload.yaml"
test_step "Network workload playbook" "test -f ~/ansible-benchmark/playbooks/network_workload.yaml"

echo
echo "=== VALIDATION SUMMARY ==="
echo "Total Tests: $((PASS_COUNT + FAIL_COUNT))"
echo "Passed: $PASS_COUNT"
echo "Failed: $FAIL_COUNT"

if [ $FAIL_COUNT -eq 0 ]; then
    echo "🎉 ALL TESTS PASSED! Environment is ready for benchmarking."
else
    echo "⚠ Some tests failed. Please check the configuration."
fi

# Return exit code based on test results
if [ $FAIL_COUNT -eq 0 ]; then
    exit 0
else
    exit 1
fi
