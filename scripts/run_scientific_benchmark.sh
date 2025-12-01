#!/bin/bash

# Scientific SSH Backend Benchmark Runner
# Complete statistical benchmarking workflow

set -e  # Exit on error

# Configuration
OUTPUT_DIR="${1:-~/ansible-benchmark/results/scientific_benchmark_$(date +%Y%m%d_%H%M%S)}"
PARALLEL="${2:-1}"
WARMUP_ITERATIONS=3
MEASUREMENT_ITERATIONS=5

echo "=================================================="
echo "    SCIENTIFIC SSH BACKEND BENCHMARK SUITE"
echo "=================================================="
echo ""
echo "Configuration:"
echo "  Output Directory: $OUTPUT_DIR"
echo "  Parallel Executions: $PARALLEL"
echo "  Warm-up Iterations: $WARMUP_ITERATIONS"
echo "  Measurement Iterations: $MEASUREMENT_ITERATIONS"
echo ""
echo "This will perform statistically rigorous comparison of:"
echo "  - ControlPersist (OpenSSH native)"
echo "  - Paramiko (Python SSH)"
echo ""
echo "Workloads to test:"
echo "  1. Connection-intensive tasks"
echo "  2. Data-transfer intensive tasks"
echo "  3. Computation-intensive tasks"
echo "  4. Real-world mixed workloads"
echo ""
echo "Scaling scenarios: 1, 3, 5, 10, 15, 20 nodes"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Log configuration
cat > "$OUTPUT_DIR/benchmark_config.json" << CONFIG_EOF
{
  "start_time": "$(date -Iseconds)",
  "output_dir": "$OUTPUT_DIR",
  "parallel_executions": $PARALLEL,
  "warmup_iterations": $WARMUP_ITERATIONS,
  "measurement_iterations": $MEASUREMENT_ITERATIONS,
  "system_info": {
    "hostname": "$(hostname)",
    "kernel": "$(uname -r)",
    "cpu_cores": $(nproc),
    "memory_mb": $(free -m | awk '/^Mem:/{print $2}'),
    "lxd_version": "$(lxc --version 2>/dev/null || echo 'not_available')"
  }
}
CONFIG_EOF

echo ""
echo "Starting benchmark suite..."
echo "All results will be saved to: $OUTPUT_DIR"
echo ""

# Step 1: System preparation
echo "=== STEP 1: System Preparation ==="
echo "1.1 Checking system requirements..."
./scripts/check_system_requirements.sh

echo "1.2 Ensuring all target nodes are ready..."
./scripts/ensure_nodes_ready.sh

echo "1.3 Setting up measurement infrastructure..."
python3 ~/ansible-benchmark/statistical_model/measurement_collector.py --setup

# Step 2: Warm-up runs (not measured)
echo ""
echo "=== STEP 2: Warm-up Runs ==="
echo "Performing $WARMUP_ITERATIONS warm-up iterations per configuration..."
echo "(These runs prime the system and are not included in measurements)"

python3 ~/ansible-benchmark/statistical_model/data_collection_workflow.py \
    --output-dir "$OUTPUT_DIR/warmup" \
    --sequential \
    --warmup-only 2>&1 | tee "$OUTPUT_DIR/warmup_log.txt"

# Step 3: Measurement runs
echo ""
echo "=== STEP 3: Measurement Runs ==="
echo "Performing $MEASUREMENT_ITERATIONS measurement iterations per configuration..."
echo "(These runs are timed and will be used for statistical analysis)"

if [ "$PARALLEL" -gt 1 ]; then
    echo "Running with $PARALLEL parallel executions..."
    python3 ~/ansible-benchmark/statistical_model/data_collection_workflow.py \
        --output-dir "$OUTPUT_DIR/measurements" \
        --parallel "$PARALLEL" 2>&1 | tee "$OUTPUT_DIR/measurement_log.txt"
else
    echo "Running sequentially..."
    python3 ~/ansible-benchmark/statistical_model/data_collection_workflow.py \
        --output-dir "$OUTPUT_DIR/measurements" \
        --sequential 2>&1 | tee "$OUTPUT_DIR/measurement_log.txt"
fi

# Step 4: Statistical analysis
echo ""
echo "=== STEP 4: Statistical Analysis ==="
echo "Performing rigorous statistical analysis of results..."

ANALYSIS_DIR="$OUTPUT_DIR/analysis"
mkdir -p "$ANALYSIS_DIR"

python3 ~/ansible-benchmark/statistical_model/statistical_analyzer.py \
    --data-dir "$OUTPUT_DIR/measurements" \
    --output-dir "$ANALYSIS_DIR" \
    --full-report 2>&1 | tee "$OUTPUT_DIR/analysis_log.txt"

# Step 5: Generate reports
echo ""
echo "=== STEP 5: Report Generation ==="
echo "Generating comprehensive reports..."

# Generate summary report
cat > "$OUTPUT_DIR/executive_summary.md" << SUMMARY_EOF
# SSH Backend Benchmarking - Executive Summary

## Test Configuration
- **Date**: $(date)
- **Duration**: $(($(date +%s) - $(date -d "$(grep start_time "$OUTPUT_DIR/benchmark_config.json" | cut -d'"' -f4)" +%s))) seconds
- **Total Experiments**: $(find "$OUTPUT_DIR/measurements" -name "metadata.json" | wc -l)
- **Success Rate**: $(grep -c '"status": "success"' "$OUTPUT_DIR/measurements/*/metadata.json" 2>/dev/null || echo 0)/$(find "$OUTPUT_DIR/measurements" -name "metadata.json" | wc -l)

## Key Findings
(Statistical analysis results will be summarized here)

## Recommendations
Based on the statistical analysis, the following recommendations are made:

1. **For production environments with repetitive tasks**: Use ControlPersist for better connection reuse
2. **For development/debugging**: Use Paramiko for better error messages
3. **For mixed workloads**: Consider workload characteristics when choosing backend
4. **For large-scale deployments**: Test both backends with your specific workload pattern

## Next Steps
1. Review the detailed statistical analysis in: $ANALYSIS_DIR/
2. Examine visualizations for insights
3. Consider running extended tests for edge cases
4. Document findings for team knowledge sharing
SUMMARY_EOF

# Copy analysis report
if [ -f "$ANALYSIS_DIR/statistical_analysis_report.md" ]; then
    cp "$ANALYSIS_DIR/statistical_analysis_report.md" "$OUTPUT_DIR/detailed_analysis.md"
fi

# Create a simple results overview
python3 -c "
import json
import os
results_dir = '$OUTPUT_DIR/measurements'
experiments = []

for root, dirs, files in os.walk(results_dir):
    if 'metadata.json' in files:
        with open(os.path.join(root, 'metadata.json'), 'r') as f:
            data = json.load(f)
            if 'experiment' in data:
                exp = data['experiment']
                experiments.append({
                    'id': exp.get('experiment_id', ''),
                    'backend': exp.get('ssh_backend', ''),
                    'nodes': exp.get('node_count', 0),
                    'workload': exp.get('workload_type', ''),
                    'duration': exp.get('end_time_ns', 0) - exp.get('start_time_ns', 0) if exp.get('end_time_ns') else 0
                })

# Group and summarize
from collections import defaultdict
summary = defaultdict(list)
for exp in experiments:
    key = f\"{exp['backend']}_{exp['nodes']}nodes_{exp['workload']}\"
    summary[key].append(exp['duration'] / 1e9)  # Convert to seconds

# Write summary
with open('$OUTPUT_DIR/results_overview.csv', 'w') as f:
    f.write('configuration,count,mean_duration,std_duration\\n')
    for key, durations in summary.items():
        if durations:
            import statistics
            mean = statistics.mean(durations)
            std = statistics.stdev(durations) if len(durations) > 1 else 0
            f.write(f'{key},{len(durations)},{mean:.2f},{std:.2f}\\n')

print(f'Results overview saved to: $OUTPUT_DIR/results_overview.csv')
"

echo ""
echo "=================================================="
echo "          BENCHMARK SUITE COMPLETE"
echo "=================================================="
echo ""
echo "Results and analysis available in:"
echo "  $OUTPUT_DIR"
echo ""
echo "Key files:"
echo "  - executive_summary.md          - High-level findings"
echo "  - detailed_analysis.md          - Statistical analysis"
echo "  - results_overview.csv          - Quick results overview"
echo "  - analysis/visualizations/      - Charts and graphs"
echo ""
echo "To review the results:"
echo "  1. cat $OUTPUT_DIR/executive_summary.md"
echo "  2. open $OUTPUT_DIR/analysis/visualizations/*.png"
echo "  3. python3 ~/ansible-benchmark/statistical_model/statistical_analyzer.py \\"
echo "     --data-dir $OUTPUT_DIR/measurements --output-dir $OUTPUT_DIR/custom_analysis"
echo ""
echo "Thank you for running the Scientific SSH Benchmark Suite!"
echo "=================================================="
