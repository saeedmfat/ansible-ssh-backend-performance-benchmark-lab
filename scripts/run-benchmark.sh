#!/bin/bash

BACKEND="$1"
SCALING_GROUP="$2"
ITERATION="${3:-1}"
OUTPUT_DIR="${4:-~/ansible-benchmark/results}"

if [ -z "$BACKEND" ] || [ -z "$SCALING_GROUP" ]; then
    echo "Usage: $0 <backend> <scaling_group> [iteration] [output_dir]"
    echo "Backends: controlpersist, paramiko"
    echo "Scaling groups: targets_1, targets_3, targets_5, targets_10, targets_15, targets_20"
    exit 1
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$OUTPUT_DIR"

echo "=== BENCHMARK RUN ==="
echo "Backend: $BACKEND"
echo "Scaling group: $SCALING_GROUP" 
echo "Iteration: $ITERATION"
echo "Timestamp: $TIMESTAMP"
echo "Output: $OUTPUT_DIR"
echo

# Set SSH backend
echo "Setting SSH backend to $BACKEND..."
~/ansible-benchmark/scripts/set-ssh-backend.sh "$BACKEND" > /dev/null 2>&1

# Start monitoring
echo "Starting resource monitoring..."
~/ansible-benchmark/scripts/start-monitoring.sh "$OUTPUT_DIR" > /dev/null 2>&1 &
sleep 5

# Create a comprehensive test playbook
TEST_PLAYBOOK="$OUTPUT_DIR/benchmark_${BACKEND}_${SCALING_GROUP}_${ITERATION}.yaml"
cat > "$TEST_PLAYBOOK" << PLAYBOOK_EOF
---
- name: SSH Backend Benchmark - $BACKEND - $SCALING_GROUP
  hosts: $SCALING_GROUP
  gather_facts: false
  serial: 1
  
  tasks:
    - name: Create test directory
      file:
        path: /tmp/ansible_benchmark
        state: directory
        mode: '0755'
      
    - name: CPU intensive task - Calculate primes
      shell: |
        python3 -c "
        import time
        start = time.time()
        def is_prime(n):
            if n < 2: return False
            for i in range(2, int(n**0.5) + 1):
                if n % i == 0: return False
            return True
        primes = [i for i in range(2, 5000) if is_prime(i)]
        duration = time.time() - start
        print(f'Found {len(primes)} primes in {duration:.2f} seconds')
        "
      register: prime_result
      ignore_errors: yes
      
    - name: File operations - Create multiple files
      file:
        path: "/tmp/ansible_benchmark/file_{{ item }}.txt"
        state: touch
      loop: "{{ range(1, 21) | list }}"
      
    - name: File content operations
      copy:
        content: "Benchmark test data on {{ inventory_hostname }}\nTimestamp: {{ ansible_date_time.epoch }}\nIteration: $ITERATION\nBackend: $BACKEND"
        dest: "/tmp/ansible_benchmark/benchmark_data.txt"
      
    - name: System information collection
      shell: |
        echo "=== System Info ==="
        echo "Hostname: \$(hostname)"
        echo "CPU Cores: \$(nproc)"
        echo "Memory: \$(free -h | grep Mem | awk '{print \$2}')"
        echo "Disk: \$(df -h / | tail -1 | awk '{print \$2}')"
        echo "Uptime: \$(uptime -p)"
      register: sysinfo
      
    - name: Network connectivity test
      wait_for:
        host: "8.8.8.8"
        port: 53
        timeout: 5
      
    - name: Service management test
      systemd:
        name: ssh
        state: restarted
        
    - name: Package information
      shell: |
        dpkg -l | wc -l
      register: package_count
      
    - name: User and process check
      shell: |
        echo "Users: \$(who | wc -l)"
        echo "Processes: \$(ps aux | wc -l)"
      register: process_info
      
    - name: Cleanup test files
      file:
        path: /tmp/ansible_benchmark
        state: absent
        
    - name: Record benchmark completion
      debug:
        msg: "Benchmark completed on {{ inventory_hostname }}"
PLAYBOOK_EOF

echo "Running benchmark playbook..."
START_TIME=$(date +%s.%N)

# Run the playbook and capture output
cd ~/ansible-benchmark
ansible-playbook "$TEST_PLAYBOOK" > "$OUTPUT_DIR/playbook_output_${BACKEND}_${SCALING_GROUP}_${ITERATION}.log" 2>&1
PLAYBOOK_EXIT_CODE=$?

END_TIME=$(date +%s.%N)
DURATION=$(echo "$END_TIME - $START_TIME" | bc)

# Stop monitoring
~/ansible-benchmark/scripts/stop-monitoring.sh > /dev/null 2>&1

# Record results
echo "$TIMESTAMP,$BACKEND,$SCALING_GROUP,$ITERATION,$DURATION,$PLAYBOOK_EXIT_CODE" >> "$OUTPUT_DIR/benchmark_results.csv"

echo
echo "=== BENCHMARK COMPLETE ==="
echo "Duration: $DURATION seconds"
echo "Exit Code: $PLAYBOOK_EXIT_CODE"
echo "Results saved to: $OUTPUT_DIR/benchmark_results.csv"
echo "Playbook log: $OUTPUT_DIR/playbook_output_${BACKEND}_${SCALING_GROUP}_${ITERATION}.log"

if [ $PLAYBOOK_EXIT_CODE -eq 0 ]; then
    echo "✓ Benchmark completed successfully"
else
    echo "⚠ Benchmark completed with warnings/errors"
fi
