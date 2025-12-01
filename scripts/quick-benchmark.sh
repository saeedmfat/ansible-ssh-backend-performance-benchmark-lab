#!/bin/bash

echo "=== QUICK BENCHMARK TEST ==="
echo "Running 2 iterations for ControlPersist backend across scaling groups..."

SCALING_GROUPS=("targets_1" "targets_3" "targets_5")
BACKEND="controlpersist"
ITERATIONS=2

for group in "${SCALING_GROUPS[@]}"; do
    for iteration in $(seq 1 $ITERATIONS); do
        echo
        echo "--- Running: $BACKEND / $group / Iteration $iteration ---"
        ~/ansible-benchmark/scripts/run-benchmark.sh "$BACKEND" "$group" "$iteration"
        echo "Cooling down..."
        sleep 5
    done
done

echo
echo "=== QUICK BENCHMARK COMPLETE ==="
echo "Results: ~/ansible-benchmark/results/benchmark_results.csv"
echo "Use: cat ~/ansible-benchmark/results/benchmark_results.csv"
