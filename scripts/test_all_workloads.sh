#!/bin/bash

echo "=== Comprehensive SSH Backend Benchmark Test ==="
echo "This will test all workloads with both backends"
echo ""

# Test each workload with both backends
for WORKLOAD in connection_intensive data_transfer_intensive mixed_realworld; do
    for BACKEND in ssh paramiko; do
        echo ""
        echo ">>> Testing: $WORKLOAD with $BACKEND <<<"
        echo "=========================================="
        
        ~/ansible-benchmark/scripts/run_workload.sh "$WORKLOAD" "$BACKEND" "targets_1"
        
        # Wait a bit between tests
        sleep 5
    done
done

echo ""
echo "=== All Tests Complete ==="
echo "Summary CSV: /tmp/benchmark_measurements.csv"
echo "View results: cat /tmp/benchmark_measurements.csv"
